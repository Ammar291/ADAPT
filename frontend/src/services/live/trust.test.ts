import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { SourceLink } from "@/components/ui/SourceLink";
import { culturalTrustLabel } from "@/components/ui/TrustBadge";
import { safeWebUrl } from "@/domain/common";
import type { DiscoverItem } from "@/domain/discover";
import { isStale } from "@/features/discover/lib/discover";
import { isRealtimeEndpoint, RealtimeConnection } from "@/features/voice/realtime/connection";
import { readActionOutcome } from "@/features/voice/api";
import { toGovernanceGraph } from "./governanceFormat";
import { toActionRecord, toJourney } from "./journeys";

describe("external outcome honesty", () => {
  const action = { id: "a1", task_key: "service.visa", type: "government_portal", title: "Visa",
    status: "completed", official_url: "https://icp.gov.ae/", external_reference: "TYPED-1",
    confirmation_source: "user_reported", is_simulated: false };

  it.each(["submitted", "completed"])("user reports cannot display %s", (status) => {
    expect(toActionRecord({ ...action, status })).toMatchObject({ status: "handoff_required", externalReference: null });
  });

  it("a simulated adapter can never display completed", () => {
    expect(toActionRecord({ ...action, confirmation_source: "adapter", is_simulated: true }).status).toBe("handoff_required");
  });

  it("voice cannot announce a user-reported outcome as completed", () => {
    expect(readActionOutcome({ ...action, message: "Completed" })).toMatchObject({ status: "handoff_required", message: null });
  });

  it("a real adapter receipt can display completed", () => {
    expect(toActionRecord({ ...action, confirmation_source: "adapter" })).toMatchObject({ status: "completed", externalReference: "TYPED-1" });
  });

  it("a stale completed journey projection cannot override unverified action status", () => {
    const journey = toJourney({ id: "j1", status: "draft", actions: [action],
      nodes: [{ id: "n1", key: action.task_key, kind: "task", status: "done", title: "Visa" }] });
    expect(journey.nodes[0]?.status).toBe("prepared");
    expect(journey.nodes[0]?.action?.status).toBe("handoff_required");
  });

  it("prepared appointments display Ready to book", () => {
    const journey = toJourney({ id: "j1", status: "draft", actions: [{ ...action, type: "appointment", status: "prepared" }],
      nodes: [{ id: "n1", key: action.task_key, kind: "appointment", status: "ready", title: "Biometrics" }] });
    expect(journey.nodes[0]?.action?.label).toBe("Ready to book");
  });
});

describe("source and cultural evidence", () => {
  it("uses four distinct cultural labels", () => {
    expect(["authoritative_requirement", "official_guidance", "community_web", "ai_recommendation"]
      .map((kind) => culturalTrustLabel(kind as Parameters<typeof culturalTrustLabel>[0])))
      .toEqual(["Official rule", "Official guidance", "Social practice", "AI recommendation"]);
  });

  it("preserves RAG passage metadata and paraphrase classification", () => {
    const graph = toGovernanceGraph({
      nodes: [{ id: "n1", key: "service.visa", entity_type: "service", label: "Visa", evidence_kind: "official_guidance", evidence_ids: ["ev1"] }],
      evidence: [{ id: "ev1", source_url: "https://icp.gov.ae/", source_title: "ICP requirements", authority: "ICP",
        section_or_page: "Documents", retrieved_at: "2026-09-29T00:00:00Z", effective_date: "2026-01-01",
        excerpt: "paraphrase", freshness: "stale", claim: "Passage", chunk_id: "chunk1" }],
    });
    expect(graph.nodes[0]?.evidence?.citations[0]).toMatchObject({ title: "ICP requirements", url: "https://icp.gov.ae/",
      authority: "ICP", section: "Documents", retrievedAt: "2026-09-29T00:00:00Z", effectiveDate: "2026-01-01",
      excerpt: "paraphrase", freshness: "stale", chunkId: "chunk1" });
  });

  it.each(["2027-01-01", "invalid-date", "2026-01-01"])("flags impossible, missing and old check dates (%s)", (lastCheckedAt) => {
    expect(isStale({ lastCheckedAt, needsRecheck: false } as DiscoverItem, new Date("2026-10-02"))).toBe(true);
  });

  it("shows source and last checked metadata", () => {
    const html = renderToStaticMarkup(createElement(SourceLink, {
      title: "Community source", url: "https://club.example.org/", checkedAt: "2026-09-29T00:00:00Z", authority: "Club",
    }));
    expect(html).toContain("Community source");
    expect(html).toContain("club.example.org");
    expect(html).toContain("Last checked");
  });
});

describe("credential destinations", () => {
  it.each(["javascript:alert(1)", "data:text/html,passport", "file:///passport.pdf", "https://user:secret@example.org/"])("refuses unsafe source links (%s)", (value) => {
    expect(safeWebUrl(value)).toBeNull();
    expect(renderToStaticMarkup(createElement(SourceLink, { title: "Source", url: value }))).not.toContain("href=");
  });

  it.each(["https://api.openai.com.evil.test/v1/realtime/calls", "https://api.openai.com/v1/realtime/calls?redirect=evil", "http://api.openai.com/v1/realtime/calls"])("never sends voice credentials to %s", (url) => {
    expect(isRealtimeEndpoint(url)).toBe(false);
  });

  it("rejects an untrusted voice endpoint before opening media or sending a credential", async () => {
    await expect(RealtimeConnection.connect({ webrtcUrl: "https://evil.test", clientSecret: "ephemeral" } as Parameters<typeof RealtimeConnection.connect>[0]))
      .rejects.toThrow("not trusted");
    expect(isRealtimeEndpoint("https://api.openai.com/v1/realtime/calls")).toBe(true);
  });
});
