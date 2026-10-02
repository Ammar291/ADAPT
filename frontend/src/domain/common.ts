/**
 * Frontend domain model — shared vocabulary.
 *
 * The UI depends on these types, never on `@adapt/contracts` directly. Live service adapters
 * (`src/services/live`) translate API payloads into this model, so backend contract changes
 * are absorbed in one place. Mock services (`src/services/mock`) produce the same types.
 */

/** Trust tier of any claim shown to a user. Mirrors the backend `EvidenceKind`. */
export type EvidenceKind =
  | "authoritative_requirement"
  | "official_guidance"
  | "community_web"
  | "ai_recommendation";

export interface Citation {
  title: string;
  url: string;
  authority: string | null;
  /** When ADAPT last retrieved or checked the source (ISO date-time). */
  retrievedAt: string | null;
  section: string | null;
  quote: string | null;
  excerpt?: "quote" | "paraphrase";
  effectiveDate?: string | null;
  freshness?: "current" | "stale" | "undated" | string;
  sourceFamily?: string | null;
  chunkId?: string | null;
}

/** Why a claim can be trusted: its tier, the sources behind it and any caveat. */
export interface Evidence {
  kind: EvidenceKind;
  citations: Citation[];
  confidence: number | null;
  note: string | null;
}

/** Areas of life a move touches. Each is a "line" on the journey map. */
export type LifeArea =
  | "business"
  | "residency"
  | "family"
  | "housing"
  | "health"
  | "finance"
  | "daily_life"
  | "community";

export const LIFE_AREAS: LifeArea[] = [
  "business",
  "residency",
  "family",
  "housing",
  "health",
  "finance",
  "daily_life",
  "community",
];

export const LIFE_AREA_LABEL: Record<LifeArea, string> = {
  business: "Business",
  residency: "Residency",
  family: "Family",
  housing: "Housing",
  health: "Health",
  finance: "Money",
  daily_life: "Daily life",
  community: "Community",
};

export type ConsentStatus = "not_asked" | "granted" | "declined";

/** Journey-agent action types, plus `communication` for messages ADAPT drafts for you. */
export type ActionKind = "government_portal" | "appointment" | "document_submission" | "official_handoff" | "communication";

export const ACTION_KIND_LABEL: Record<ActionKind, string> = {
  government_portal: "Government portal",
  appointment: "Appointment",
  document_submission: "Document submission",
  official_handoff: "Official handoff",
  communication: "Message",
};

/**
 * Lifecycle of an action ADAPT prepares. `submitted` and `completed` require a real external
 * reference; simulated adapters can never reach them. `handoff_required` means the user
 * finishes on the official channel (e.g. with UAE PASS).
 */
export type ActionStatus =
  | "draft"
  | "prepared"
  | "awaiting_approval"
  | "approved"
  | "submitted"
  | "completed"
  | "blocked"
  | "failed"
  | "handoff_required"
  | "rejected"
  | "cancelled";

/** The host part of a URL, for compact source labels ("tamm.abudhabi"). */
export function safeWebUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return ["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null;
  } catch {
    return null;
  }
}

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
