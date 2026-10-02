import type { LifeArea } from "./common";
import type { Journey, RiskKind, RiskSeverity } from "./journey";

export interface AssumptionChange {
  key: string;
  value: unknown;
}

export interface NodeChange {
  key: string;
  title: string;
  /** Changed fields, e.g. `status`, `dueBy`, `dependencies`. */
  fields: string[];
}

export interface DependencyChange {
  /** The dependent step. */
  source: string;
  /** Its prerequisite. */
  target: string;
  sourceTitle: string;
  targetTitle: string;
  relation: string;
  change: "added" | "removed";
}

export interface RiskChange {
  id: string;
  kind: RiskKind;
  title: string;
  severity: RiskSeverity;
  change: "added" | "removed" | "changed";
}

export interface ScenarioTask {
  key: string;
  title: string;
  area: LifeArea;
}

/** What a what-if changes compared with the current plan. */
export interface ScenarioDiff {
  summary: string;
  /** The assumptions that were changed. */
  changes: { key: string; label: string; from: string; to: string }[];
  /** Agent stages that re-ran for this scenario. */
  rerunStages: string[];
  changedNodes: NodeChange[];
  addedTasks: ScenarioTask[];
  removedTasks: ScenarioTask[];
  changedDependencies: DependencyChange[];
  changedRisks: RiskChange[];
}

export interface ScenarioOutcome {
  base: Journey;
  scenario: Journey;
  diff: ScenarioDiff;
}

export interface SimulationProgress {
  stage: string;
  label: string;
  progress: number;
}
