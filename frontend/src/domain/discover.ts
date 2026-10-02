import type { EvidenceKind } from "./common";

export type DiscoverSection =
  | "your_communities"
  | "faith"
  | "professional"
  | "events"
  | "culture"
  | "surprises"
  | "starter_kit";

export const DISCOVER_SECTIONS: { id: DiscoverSection; title: string; description: string }[] = [
  { id: "your_communities", title: "Your Communities", description: "People who share your language, background or interests." },
  { id: "faith", title: "Your Faith & Places", description: "Places of worship and faith communities, shown only because you asked." },
  { id: "professional", title: "Your Professional Network", description: "Founder networks, industry groups and business support." },
  { id: "events", title: "Local Events", description: "Recurring and seasonal events worth planning around." },
  { id: "culture", title: "Cultural Guide", description: "Customs and etiquette, explained plainly." },
  { id: "surprises", title: "Things That May Surprise You", description: "Everyday differences newcomers often mention." },
  { id: "starter_kit", title: "Starter Kit", description: "Practical essentials for your first weeks." },
];

/** How much weight a source carries. This is the only quality signal shown; never a score. */
export type SourceLabel = "official" | "organization" | "community" | "general_web";

export const SOURCE_LABEL_TEXT: Record<SourceLabel, string> = {
  official: "Official",
  organization: "Organization",
  community: "Community",
  general_web: "General web",
};

export interface DiscoverSource {
  title: string;
  /** Null for sample catalogue content that has no public page. */
  url: string | null;
  domain: string | null;
  label: SourceLabel;
}

/** Contact details, verified against the cited page only. */
export interface DiscoverContact {
  kind: "website" | "email" | "phone" | "address";
  value: string;
  sourceUrl: string;
}

/** A single research result. Web findings always carry a source and when it was checked. */
/** How a result's source was found and checked, in words a person can verify. */
export interface DiscoverRetrieval {
  method: "curated_snapshot" | "live_web_search";
  /** e.g. "ADAPT reviewed source list" or "Live web search". */
  label: string;
  note: string;
  retrievedAt: string;
}

export interface DiscoverItem {
  id: string;
  section: DiscoverSection;
  title: string;
  summary: string;
  /** Why ADAPT thinks it fits this user. */
  relevance: string | null;
  /** The user's own facts behind the relevance (explained via the user graph). Empty when generic. */
  factIds: string[];
  source: DiscoverSource;
  moreSources: DiscoverSource[];
  lastCheckedAt: string;
  /** Last checked more than 30 days ago: may be out of date. */
  needsRecheck: boolean;
  evidenceKind: EvidenceKind;
  /** For events and places: when or where, in plain words. */
  when: string | null;
  where: string | null;
  contacts: DiscoverContact[];
  saved: boolean;
  /** Set once the user added it to their journey. */
  journeyNodeId: string | null;
  /** Illustrative catalogue content rather than a verified research result. Labelled in the UI. */
  isSample: boolean;
  /** How the source was retrieved (live results only). */
  retrieval?: DiscoverRetrieval | null;
}

export type ResearchState = "idle" | "running" | "ready" | "unavailable";

export type ResearchCategoryStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface ResearchCategoryProgress {
  section: DiscoverSection;
  status: ResearchCategoryStatus;
  count: number;
  /** e.g. `faith_not_opted_in` for a skipped faith category. */
  reason: string | null;
}

export interface ResearchStatus {
  /** `unavailable` only when the research service errors. */
  state: ResearchState;
  jobId: string | null;
  /** Subscribe to this run for live `research_*` events. */
  runId: string | null;
  /** `snapshot` = ADAPT's reviewed, URL-verified source list rather than live web research. */
  mode: "live" | "snapshot";
  itemCount: number;
  lastCheckedAt: string | null;
  /** "Your Abu Dhabi Life Brief" is ready to read. */
  briefReady: boolean;
  /** The user has seen the brief-ready notice. */
  seen: boolean;
  categories: ResearchCategoryProgress[];
  /** What personalised the results, e.g. "Work: founder". */
  personalisedWith: string[];
}

export interface StartResearchInput {
  categories?: DiscoverSection[];
  focus?: string;
}
