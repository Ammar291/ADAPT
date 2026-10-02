import { describe, expect, it } from "vitest";
import type { TwinFact } from "@/domain/graph";
import { sampleProfile } from "@/services/mock/store";
import { buildUserGraph } from "@/services/mock/twin";
import type { UserDocument } from "@/domain/documents";
import { specimenExtraction } from "@/services/mock/content";
import { overlaps } from "../layout/geometry";
import { confidenceWords, factRows, formatFactValue, isMasked, looksLikeDocumentNumber, maskValue } from "./facts";
import { buildTwinMap, centreOf, readableLabel, twinConnections } from "./model";

function sampleGraph() {
  const at = "2026-09-20T10:00:00Z";
  const doc = (id: string, kind: UserDocument["kind"], status: UserDocument["status"]): UserDocument =>
    ({
      id,
      kind,
      filename: `${id}.jpg`,
      contentType: "image/jpeg",
      sizeBytes: 1000,
      status,
      extraction: specimenExtraction(kind, new Date(at)),
      usedFor: [],
      contentUrl: null,
      createdAt: at,
    }) as UserDocument;
  return buildUserGraph(sampleProfile(new Date("2026-09-29T00:00:00Z")), [doc("doc_passport", "passport", "confirmed"), doc("doc_marriage", "marriage_certificate", "needs_review")], {
    displayName: "Sam Carter",
    observedAt: at,
    faithGranted: false,
  });
}

describe("buildTwinMap", () => {
  const graph = sampleGraph();
  const map = buildTwinMap(graph, 1.8);

  it("centres on the person and includes the public rules the twin links to", () => {
    expect(map.centreId).toBe(centreOf(graph)!.id);
    const centre = map.items.find((i) => i.id === map.centreId)!;
    expect(centre.rect.x + centre.rect.width / 2).toBeCloseTo(0);
    const publicItems = map.items.filter((i) => i.group === "public");
    expect(publicItems.length).toBe(graph.linkedNodes.length);
    expect(publicItems.every((i) => i.typeLabel === "Public rule" && i.nodeType === "public")).toBe(true);
  });

  it("draws cross-graph links differently from private ones, and blocked links as danger", () => {
    const variants = new Set(map.edges.map((e) => e.variant));
    expect(variants).toEqual(new Set(["private", "cross", "blocked"]));
    const blocked = map.edges.find((e) => e.variant === "blocked")!;
    expect(blocked.marker).toBe("danger");
    expect(blocked.pinnedLabel).toBe("blocked by");
  });

  it("does not overlap nodes", () => {
    const rects = map.items.map((i) => i.rect);
    rects.forEach((r, i) => rects.forEach((o, j) => j > i && expect(overlaps(r, o)).toBe(false)));
  });

  it("flags documents that still need review", () => {
    const marriage = map.items.find((i) => i.key === "document.doc_marriage")!;
    expect(marriage.extra.needsReview).toBe(true);
    const passport = map.items.find((i) => i.key === "document.doc_passport")!;
    expect(passport.extra.needsReview).toBe(false);
  });

  it("lists a node's links from its point of view", () => {
    const you = centreOf(graph)!;
    const titles = twinConnections(you.id, graph).map((c) => c.title);
    expect(titles).toContain("Wants to");
    expect(titles).toContain("Holds");
    const goal = graph.nodes.find((n) => n.key === "goal.sponsor_spouse")!;
    const goalLinks = twinConnections(goal.id, graph);
    expect(goalLinks.find((c) => c.title === "Blocked by")!.items[0]!.isPublic).toBe(true);
  });

  it("handles an empty twin", () => {
    const empty = buildTwinMap({ nodes: [], edges: [], linkedNodes: [], generatedAt: "" }, 1.5);
    expect(empty.items).toEqual([]);
    expect(empty.centreId).toBeNull();
  });
});

describe("facts", () => {
  const fact = (value: unknown, extra: Partial<TwinFact> = {}): TwinFact => ({
    value,
    source: "document_extracted",
    sourceRef: null,
    confidence: 0.9,
    confirmedByUser: true,
    observedAt: "2026-09-20T10:00:00Z",
    ...extra,
  });

  it("says confidence in words", () => {
    expect(confidenceWords(0.97)).toBe("High confidence");
    expect(confidenceWords(0.7)).toBe("Medium confidence");
    expect(confidenceWords(0.4)).toBe("Low confidence");
  });

  it("recognises document numbers but not dates or amounts", () => {
    expect(looksLikeDocumentNumber("certificate_number", "MC-2019-0847")).toBe(true);
    expect(looksLikeDocumentNumber("passport_number", "UT4821937")).toBe(true);
    expect(looksLikeDocumentNumber("reference", "784-1988-1234567-1")).toBe(true);
    expect(looksLikeDocumentNumber("anything", "784198812345671")).toBe(true);
    expect(looksLikeDocumentNumber("date_of_birth", "1988-04-12")).toBe(false);
    expect(looksLikeDocumentNumber("budget", "AED 9000/month")).toBe(false);
    expect(looksLikeDocumentNumber("surname", "CARTER")).toBe(false);
    expect(looksLikeDocumentNumber("passport_number", "•••• 1937")).toBe(false);
  });

  it("masks keeping the last four characters", () => {
    expect(maskValue("MC-2019-0847")).toBe("•••• 0847");
    expect(isMasked("•••• 1937")).toBe(true);
    expect(isMasked("CARTER")).toBe(false);
  });

  it("formats values for reading", () => {
    expect(formatFactValue("2031-06-30")).toBe("30 Jun 2031");
    expect(formatFactValue(true)).toBe("Yes");
    expect(formatFactValue(["English", "Arabic"])).toBe("English, Arabic");
    expect(formatFactValue(null)).toBe("Not recorded");
    expect(formatFactValue({ city: "Abu Dhabi", nested: { a: 1 } })).toBe("City: Abu Dhabi");
  });

  it("builds rows with provenance and review state", () => {
    const rows = factRows({
      certificate_number: fact("MC-2019-0847", { confidence: 0.64, confirmedByUser: false }),
      surname: fact("CARTER", { source: "user_stated" }),
    });
    expect(rows[0]).toMatchObject({ label: "Certificate number", sensitive: true, confidence: "Medium confidence", confirmed: false, source: "Read from your document" });
    expect(rows[1]).toMatchObject({ label: "Surname", sensitive: false, source: "You told ADAPT", confirmed: true });
  });
});

describe("readableLabel", () => {
  it("writes ISO dates in labels the way people read them", () => {
    expect(readableLabel("Arrive by 2026-11-12")).toBe("Arrive by 12 Nov 2026");
    expect(readableLabel("Your spouse")).toBe("Your spouse");
  });
});
