import type { ActionKind, ActionStatus, Evidence, EvidenceKind, LifeArea } from "./common";

/**
 * The journey is a dependency graph. Nodes are the things a person does, provides, books
 * or approves; edges say what must happen first.
 */
export type JourneyNodeKind =
  | "task"
  | "requirement"
  | "document"
  | "appointment"
  | "dependency"
  | "approval"
  | "action";

export const JOURNEY_NODE_KIND_LABEL: Record<JourneyNodeKind, string> = {
  task: "Task",
  requirement: "Requirement",
  document: "Document",
  appointment: "Appointment",
  dependency: "Dependency",
  approval: "Approval",
  action: "Action",
};

/**
 * One vocabulary for progress, everywhere in the UI:
 *   todo / in_progress — the user can work on it
 *   blocked            — something else must happen first
 *   prepared           — ADAPT prepared it; the user takes it from here
 *   waiting_for_me     — needs the user's answer, document or approval
 *   done               — finished
 */
export type JourneyNodeStatus =
  | "todo"
  | "in_progress"
  | "blocked"
  | "prepared"
  | "waiting_for_me"
  | "done"
  | "not_applicable";

export type BlockerKind = "missing_info" | "missing_document" | "dependency" | "eligibility" | "attestation";

export interface Blocker {
  kind: BlockerKind;
  message: string;
  resolution: string | null;
  /** Key of the journey node that resolves it, when there is one. */
  relatedNodeKey: string | null;
}

export type NodeActionKind =
  | ActionKind
  | "upload_document"
  | "answer_question"
  | "review_draft"
  | "mark_done"
  /** Opens a screen in ADAPT, or an external source when `url` is set. */
  | "navigate";

/** The single most useful next move on a node, rendered as its primary button. */
export interface NodeAction {
  id: string;
  kind: NodeActionKind;
  label: string;
  status: ActionStatus | null;
  /** Official page for handoffs. Always https on an official domain. */
  url: string | null;
  approvalId: string | null;
  draftId: string | null;
  documentKind: string | null;
  /** The user signs in on the official site (e.g. UAE PASS). ADAPT never asks for it. */
  requiresUserAuthentication: boolean;
  /** For `answer_question`: what ADAPT needs to know, phrased as a question. */
  question?: string | null;
}

export interface JourneyNode {
  id: string;
  /** Stable within a journey; used for dependencies and scenario diffs. */
  key: string;
  kind: JourneyNodeKind;
  title: string;
  summary: string;
  whyItMatters: string | null;
  area: LifeArea;
  status: JourneyNodeStatus;
  authority: string | null;
  officialUrl: string | null;
  /** ADAPT's planning estimate, not an official processing time. */
  estimatedDays: number | null;
  dueBy: string | null;
  completedAt: string | null;
  evidence: Evidence;
  blockers: Blocker[];
  action: NodeAction | null;
  governanceKey: string | null;
  /** Private facts from the user's twin that shaped this step ("why am I seeing this"). */
  factIds: string[];
  /** What ADAPT needs to know to decide something about this step, most decisive first. */
  questions?: { key: string; label: string; question: string }[];
}

export type JourneyEdgeRelation =
  | "depends_on" // target must finish before source
  | "requires" // source needs this document or requirement
  | "blocked_by" // source is blocked by this dependency
  | "books" // source is done at this appointment
  | "approves"; // source waits for this approval

export interface JourneyEdge {
  id: string;
  /** The dependent node. */
  source: string;
  /** What it depends on. */
  target: string;
  relation: JourneyEdgeRelation;
  /** Edges sharing an `anyOf` group are satisfied by any one of them. */
  anyOf: string | null;
}

export interface Assumption {
  key: string;
  label: string;
  value: unknown;
}

export interface Consideration {
  id: string;
  title: string;
  detail: string;
  area: LifeArea;
  evidence: Evidence;
}

export type RiskSeverity = "info" | "warning" | "blocking";

export type RiskKind =
  | "missing_user_document"
  | "missing_information"
  | "missing_source_evidence"
  | "timeline_dependency"
  | "incompatible_task_ordering"
  | "external_login_required"
  | "eligibility_gap";

/** Something that could delay or derail the plan, found by risk detection. */
export interface Risk {
  id: string;
  kind: RiskKind;
  title: string;
  detail: string;
  resolution: string | null;
  severity: RiskSeverity;
  /** Journey nodes the risk affects. */
  nodeKeys: string[];
  evidence: Evidence;
}

export type JourneyStatus = "draft" | "active" | "scenario" | "archived";

export interface Journey {
  id: string;
  title: string;
  status: JourneyStatus;
  goals: string[];
  assumptions: Assumption[];
  nodes: JourneyNode[];
  edges: JourneyEdge[];
  considerations: Consideration[];
  risks: Risk[];
  parentJourneyId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface JourneySummary {
  id: string;
  title: string;
  status: JourneyStatus;
  nodeCount: number;
  completedCount: number;
  updatedAt: string;
}

/** Assumption keys shared by onboarding, the journey agent and what-if simulation. */
export const ASSUMPTION = {
  moveType: "move.type",
  arrivalDate: "move.arrival_date",
  household: "household.composition",
  children: "household.children",
  companyTiming: "company.timing",
  jurisdiction: "company.jurisdiction",
  housing: "housing.preference",
  budget: "budget.monthly_housing_aed",
  languages: "profile.languages",
} as const;

export function evidenceOf(kind: EvidenceKind, note: string | null = null): Evidence {
  return { kind, citations: [], confidence: null, note };
}
