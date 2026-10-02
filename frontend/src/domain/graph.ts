import type { Evidence } from "./common";

/** `governance` is shared public knowledge; `user` is one person's private digital twin. */
export type GraphScope = "governance" | "user";

export type FactSource = "user_stated" | "document_extracted" | "inferred" | "system";

export interface TwinFact {
  value: unknown;
  source: FactSource;
  sourceRef: string | null;
  confidence: number;
  confirmedByUser: boolean;
  observedAt: string | null;
}

export interface KnowledgeNode {
  id: string;
  key: string;
  scope: GraphScope;
  /** Entity type, e.g. `service`, `authority`, `person`, `goal`. */
  type: string;
  label: string;
  summary: string | null;
  properties: Record<string, unknown>;
  evidence: Evidence | null;
  officialUrl: string | null;
  /** Private facts, for user-graph nodes only. */
  facts: Record<string, TwinFact>;
}

export interface KnowledgeEdge {
  id: string;
  scope: GraphScope;
  source: string;
  target: string;
  relation: string;
  label: string | null;
  anyOf: string | null;
  /** Conditions on the relation, e.g. `when` (applies only if…) and `party` (sponsor, beneficiary). */
  properties?: Record<string, unknown>;
}

export interface KnowledgeGraph {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  /** For the user graph: public governance nodes the twin links to. */
  linkedNodes: KnowledgeNode[];
  generatedAt: string;
}

export interface KnowledgeNodeDetail {
  node: KnowledgeNode;
  neighbours: KnowledgeNode[];
  edges: KnowledgeEdge[];
}

export const GOVERNANCE_TYPE_LABEL: Record<string, string> = {
  authority: "Authority",
  service: "Service",
  requirement: "Requirement",
  document: "Document",
  document_type: "Document",
  eligibility_rule: "Eligibility rule",
  appointment: "Appointment",
  dependency: "Dependency",
  portal: "Where to apply",
  official_channel: "Where to apply",
  process_step: "Process step",
  fee: "Fee",
  legal_instrument: "Law or decree",
  location: "Jurisdiction",
  source: "Official source",
};

/** Governance node types that are citations rather than rules; hidden from maps by default. */
export const GOVERNANCE_SOURCE_TYPES = new Set(["source"]);

export const USER_TYPE_LABEL: Record<string, string> = {
  person: "Person",
  organization: "Organisation",
  document: "Document",
  goal: "Goal",
  preference: "Preference",
  constraint: "Constraint",
  milestone: "Milestone",
};

export const RELATION_LABEL: Record<string, string> = {
  provided_by: "provided by",
  provides: "provides",
  available_at: "available at",
  may_require: "may require",
  satisfied_by: "satisfied by",
  evidenced_by: "cited in",
  requires: "requires",
  depends_on: "depends on",
  produces: "produces",
  applies_to: "applies to",
  available_via: "available via",
  governed_by: "governed by",
  located_in: "located in",
  spouse_of: "spouse of",
  dependent_of: "dependent of",
  founder_of: "founder of",
  holds_document: "holds",
  has_goal: "wants to",
  prefers: "prefers",
  constrained_by: "constrained by",
  pursues: "pursues",
  satisfies: "satisfies",
  instance_of: "is a",
  eligible_for: "eligible for",
  blocked_by: "blocked by",
};

export const FACT_SOURCE_LABEL: Record<FactSource, string> = {
  user_stated: "You told ADAPT",
  document_extracted: "Read from your document",
  inferred: "ADAPT inferred",
  system: "Set by ADAPT",
};
