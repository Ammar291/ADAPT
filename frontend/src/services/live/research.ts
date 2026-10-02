/**
 * Live Discover service: background Abu Dhabi research (`/api/research*`, `/api/discover`).
 * The only code that knows the research wire format; it maps it into `@/domain/discover`.
 *
 * Research runs in the backend worker; nothing here waits for it. `start()` returns as soon
 * as the job is queued, and progress arrives as `research_*` events on the job's run.
 */
import type { EvidenceKind } from "@/domain/common";
import type {
  DiscoverContact,
  DiscoverItem,
  DiscoverSection,
  DiscoverSource,
  ResearchCategoryProgress,
  ResearchCategoryStatus,
  ResearchStatus,
  SourceLabel,
  StartResearchInput,
} from "@/domain/discover";
import { api } from "@/lib/api/client";
import type { DiscoverService } from "../types";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** Research routes, relative to `config.apiBaseUrl` (candidates for `paths.ts`). */
export const researchPaths = {
  research: "/research",
  job: (id: string) => `/research/${id}`,
  seen: (id: string) => `/research/${id}/seen`,
  result: (id: string) => `/research/results/${id}`,
  addToJourney: (id: string) => `/research/results/${id}/journey`,
  discover: "/discover",
} as const;

/** Backend research category -> Discover section. */
export const CATEGORY_SECTION: Record<string, DiscoverSection> = {
  community: "your_communities",
  faith_and_worship: "faith",
  professional_network: "professional",
  events: "events",
  culture: "culture",
  lifestyle: "surprises",
  starter_kit: "starter_kit",
};

const SECTION_CATEGORY = Object.fromEntries(
  Object.entries(CATEGORY_SECTION).map(([category, section]) => [section, category]),
) as Record<DiscoverSection, string>;

function formatDay(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Event timing in plain words: stated dates, or the usual timing of a recurring event. */
export function describeWhen(event: Raw | null | undefined): string | null {
  if (!event) return null;
  const { starts_on: start, ends_on: end, timing_note: note } = event;
  if (start && end && end !== start) return `${formatDay(start)} – ${formatDay(end)}`;
  if (start) return formatDay(start);
  return note ?? null;
}

function toSource(url: string, title: string, domain: string, label: SourceLabel): DiscoverSource {
  return { url, title, domain, label };
}

export function toDiscoverItem(raw: Raw): DiscoverItem {
  const citations: Raw[] = raw.citations ?? [];
  return {
    id: raw.id,
    section: CATEGORY_SECTION[raw.category] ?? "your_communities",
    title: raw.title,
    summary: raw.summary,
    relevance: raw.relevance || null,
    // The user's own stored facts behind `relevance` (explain via /graph/user/explain).
    factIds: raw.fact_ids ?? [],
    source: toSource(raw.source_url, raw.source_title, raw.source_domain, raw.source_label),
    moreSources: citations
      .filter((c) => !c.is_primary)
      .map((c) => toSource(c.url, c.title, c.source_domain, c.source_label)),
    lastCheckedAt: raw.retrieved_at,
    needsRecheck: Boolean(raw.needs_recheck),
    evidenceKind: raw.evidence_kind as EvidenceKind,
    when: describeWhen(raw.event),
    where: null,
    contacts: (raw.contacts ?? []).map(
      (c: Raw): DiscoverContact => ({ kind: c.kind, value: c.value, sourceUrl: c.source_url }),
    ),
    saved: Boolean(raw.saved),
    journeyNodeId: raw.journey_node_id ?? null,
    isSample: false, // every research result cites a real, checked page
    retrieval: raw.retrieval
      ? {
          method: raw.retrieval.method === "live_web_search" ? "live_web_search" : "curated_snapshot",
          label: String(raw.retrieval.label ?? ""),
          note: String(raw.retrieval.note ?? ""),
          retrievedAt: raw.retrieval.retrieved_at ?? raw.retrieved_at,
        }
      : null,
  };
}

const IDLE: ResearchStatus = {
  state: "idle",
  jobId: null,
  runId: null,
  mode: "snapshot",
  itemCount: 0,
  lastCheckedAt: null,
  briefReady: false,
  seen: false,
  categories: [],
  personalisedWith: [],
};

export function toResearchStatus(job: Raw | null | undefined): ResearchStatus {
  if (!job) return IDLE;
  const running = job.status === "queued" || job.status === "running";
  const failed = job.status === "failed" || job.status === "cancelled";
  return {
    state: running ? "running" : failed ? "unavailable" : "ready",
    jobId: job.id,
    runId: job.run_id,
    mode: job.mode === "live" ? "live" : "snapshot",
    itemCount: job.result_count ?? 0,
    lastCheckedAt: job.completed_at ?? null,
    briefReady: Boolean(job.brief_ready),
    seen: job.seen_at != null,
    categories: (job.categories ?? []).map(
      (c: Raw): ResearchCategoryProgress => ({
        section: CATEGORY_SECTION[c.category] ?? "your_communities",
        status: c.status as ResearchCategoryStatus,
        count: c.result_count ?? 0,
        reason: c.reason ?? null,
      }),
    ),
    personalisedWith: job.personalised_with ?? [],
  };
}

/** Latest brief's results plus earlier saved ones, each once. */
export function itemsFromDiscover(page: Raw): DiscoverItem[] {
  const seen = new Set<string>();
  const items: DiscoverItem[] = [];
  const all: Raw[] = [...(page.sections ?? []).flatMap((s: Raw) => s.results ?? []), ...(page.saved ?? [])];
  for (const raw of all) {
    if (seen.has(raw.id)) continue;
    seen.add(raw.id);
    items.push(toDiscoverItem(raw));
  }
  return items;
}

export function createLiveDiscoverService(): DiscoverService {
  return {
    async items(signal) {
      return itemsFromDiscover(await api.get<Raw>(researchPaths.discover, { signal }));
    },
    async status(signal) {
      const jobs = await api.get<Raw[]>(researchPaths.research, { query: { limit: 1 }, signal });
      return toResearchStatus(jobs[0]);
    },
    async start(input?: StartResearchInput) {
      const body: Raw = {};
      if (input?.categories?.length) body.categories = input.categories.map((s) => SECTION_CATEGORY[s]);
      if (input?.focus?.trim()) body.focus = input.focus.trim();
      const started = await api.post<Raw>(researchPaths.research, body);
      return toResearchStatus(started.job);
    },
    async save(itemId, saved) {
      return toDiscoverItem(await api.patch<Raw>(researchPaths.result(itemId), { saved }));
    },
    async addToJourney(itemId) {
      // Throws ApiError code "journey_required" when there is no journey yet.
      return toDiscoverItem(await api.post<Raw>(researchPaths.addToJourney(itemId), {}));
    },
    async markSeen(jobId) {
      await api.post<Raw>(researchPaths.seen(jobId));
    },
  };
}
