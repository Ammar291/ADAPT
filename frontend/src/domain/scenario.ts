/**
 * Scripted demo scenarios (`/demo/founder-arrival`): fixed inputs to the real API, read
 * from the backend's scenario kit so the presenter page and the rehearsal script always run
 * the same sequence. Everything the page shows comes from the real pipeline.
 */
import type { DocumentKind } from "./documents";
import type { DiscoverSection } from "./discover";

export type ScenarioRole =
  | "company"
  | "residence"
  | "document"
  | "family"
  | "appointment"
  | "official_handoff"
  | "missing_information";

export interface ScenarioFact {
  label: string;
  value: string;
  /** Stated by the persona, supplied by one of the documents, or given nowhere (ADAPT asks). */
  source: "stated" | "document" | "missing";
}

export interface ScenarioDocument {
  key: string;
  kind: DocumentKind;
  title: string;
  filename: string;
  /** The synthetic PDF, served by the scenario kit. */
  url: string;
  reads: string[];
  changes: string;
  confirm: boolean;
}

export interface ScenarioResearchGroup {
  key: string;
  title: string;
  sections: DiscoverSection[];
  description: string;
}

export interface ScenarioRoleRef {
  role: ScenarioRole;
  label: string;
  nodeKey: string;
  note: string;
}

export interface ScenarioAct {
  key: string;
  title: string;
  description: string;
}

export interface DemoScenario {
  key: string;
  title: string;
  tagline: string;
  syntheticNotice: string;
  persona: { name: string; headline: string; summary: string; facts: ScenarioFact[] };
  documents: ScenarioDocument[];
  researchGroups: ScenarioResearchGroup[];
  roles: ScenarioRoleRef[];
  whatIf: { key: string; title: string; description: string };
  acts: ScenarioAct[];
}

/** The stages a document goes through, as the audience sees them. */
export type DocumentStage = "uploaded" | "analyzed" | "facts" | "twin";

export const DOCUMENT_STAGES: { stage: DocumentStage; label: string }[] = [
  { stage: "uploaded", label: "Document uploaded" },
  { stage: "analyzed", label: "Document analyzed" },
  { stage: "facts", label: "Facts extracted" },
  { stage: "twin", label: "User graph updated" },
];

/** Reading-run node -> the audience-facing stage it completes. */
export const STAGE_OF_NODE: Record<string, DocumentStage> = {
  extract: "analyzed",
  structure: "facts",
  update_twin: "twin",
};
