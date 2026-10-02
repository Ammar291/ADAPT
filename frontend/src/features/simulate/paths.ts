import { tr } from "@/i18n";
/**
 * Pure comparison of the current plan and a what-if scenario as two paths: steps in
 * dependency order, the longest chain (critical path), and what was added, removed or
 * changed. Also finds actions that are new in the scenario (e.g. new official handoffs).
 */
import { LIFE_AREAS, type LifeArea } from "@/domain/common";
import type { Journey, JourneyNode, JourneyNodeKind, JourneyNodeStatus, NodeActionKind } from "@/domain/journey";
import type { NodeChange, ScenarioDiff } from "@/domain/simulate";
import { completion, criticalPath, criticalPathDays, depthOf, STATUS_LABEL } from "@/lib/journey/analysis";
import { formatShortDate } from "@/lib/format";

/** Things a person does; approvals and bookkeeping nodes aren't steps on the path. */
const STEP_KINDS = new Set<JourneyNodeKind>(["task", "requirement", "document", "appointment", "dependency", "action"]);

export type StepChange = "added" | "removed" | "changed" | null;

export interface PathStep {
  key: string;
  title: string;
  area: LifeArea;
  kind: JourneyNodeKind;
  status: JourneyNodeStatus;
  depth: number;
  critical: boolean;
  estimatedDays: number | null;
  change: StepChange;
  changedFields: string[];
}

export interface PathSummary {
  steps: PathStep[];
  criticalDays: number;
  completion: { done: number; total: number; percent: number };
}

function areaIndex(area: LifeArea): number {
  const i = LIFE_AREAS.indexOf(area);
  return i < 0 ? LIFE_AREAS.length : i;
}

function byPathOrder(a: { depth: number; area: LifeArea; title: string }, b: { depth: number; area: LifeArea; title: string }): number {
  return a.depth - b.depth || areaIndex(a.area) - areaIndex(b.area) || a.title.localeCompare(b.title);
}

/** One side of the comparison, ordered by dependency depth. */
export function pathSummary(journey: Journey, diff: ScenarioDiff, side: "base" | "scenario"): PathSummary {
  const depth = depthOf(journey);
  const critical = new Set(criticalPath(journey));
  const added = new Set(diff.addedTasks.map((t) => t.key));
  const removed = new Set(diff.removedTasks.map((t) => t.key));
  const changed = new Map(diff.changedNodes.map((c) => [c.key, c.fields]));
  const steps = journey.nodes
    .filter((n) => STEP_KINDS.has(n.kind) && n.status !== "not_applicable")
    .map((n): PathStep => {
      const change: StepChange =
        side === "scenario" && added.has(n.key) ? "added" : side === "base" && removed.has(n.key) ? "removed" : changed.has(n.key) ? "changed" : null;
      return {
        key: n.key,
        title: n.title,
        area: n.area,
        kind: n.kind,
        status: n.status,
        depth: depth.get(n.key) ?? 0,
        critical: critical.has(n.key),
        estimatedDays: n.estimatedDays,
        change,
        changedFields: change === "changed" ? (changed.get(n.key) ?? []) : [],
      };
    })
    .sort(byPathOrder);
  return { steps, criticalDays: criticalPathDays(journey), completion: completion(journey) };
}

export interface AlignedRow {
  key: string;
  base: PathStep | null;
  scenario: PathStep | null;
}

/**
 * Both paths as aligned rows, so the same step sits on the same line in each column.
 * Ordered by the scenario's dependency depth (the base's for removed steps).
 */
export function alignPaths(base: PathSummary, scenario: PathSummary): AlignedRow[] {
  const baseByKey = new Map(base.steps.map((s) => [s.key, s]));
  const scenarioByKey = new Map(scenario.steps.map((s) => [s.key, s]));
  const keys = new Set([...scenario.steps.map((s) => s.key), ...base.steps.map((s) => s.key)]);
  return [...keys]
    .map((key) => ({ key, base: baseByKey.get(key) ?? null, scenario: scenarioByKey.get(key) ?? null }))
    .sort((a, b) => byPathOrder((a.scenario ?? a.base)!, (b.scenario ?? b.base)!));
}

/** Rows worth showing by default: anything that changed, plus either plan's longest chain. */
export function focusRows(rows: AlignedRow[]): AlignedRow[] {
  return rows.filter((row) => row.base?.change || row.scenario?.change || row.base?.critical || row.scenario?.critical);
}

export function focusSteps(steps: PathStep[]): PathStep[] {
  return steps.filter((s) => s.change || s.critical);
}

// --- new actions --------------------------------------------------------------------------------------

export interface ScenarioAction {
  key: string;
  title: string;
  area: LifeArea;
  label: string;
  kind: NodeActionKind;
  url: string | null;
  requiresUserAuthentication: boolean;
  /** The whole step is new, rather than a new action on an existing step. */
  newStep: boolean;
}

/** Scenario steps whose primary action is new or different from the current plan's. */
export function newActions(base: Journey, scenario: Journey): ScenarioAction[] {
  const baseByKey = new Map(base.nodes.map((n) => [n.key, n]));
  const result: ScenarioAction[] = [];
  for (const node of scenario.nodes) {
    const action = node.action;
    if (!action || node.status === "done" || node.status === "not_applicable" || !STEP_KINDS.has(node.kind)) continue;
    const before = baseByKey.get(node.key);
    const same = before?.action && before.action.kind === action.kind && before.action.label === action.label && before.action.url === action.url;
    if (same) continue;
    result.push({
      key: node.key,
      title: node.title,
      area: node.area,
      label: action.label,
      kind: action.kind,
      url: action.url,
      requiresUserAuthentication: action.requiresUserAuthentication,
      newStep: !before,
    });
  }
  return result.sort((a, b) => Number(b.newStep) - Number(a.newStep) || areaIndex(a.area) - areaIndex(b.area));
}

// --- changed steps --------------------------------------------------------------------------------------

const FIELD_LABEL: Record<string, string> = {
  status: "Status",
  dueBy: tr("copy.target_date_e337ddc", { lng: "en" }),
  title: tr("copy.name_709a232", { lng: "en" }),
  kind: "Type",
  dependencies: tr("copy.what_it_waits_for_3a21f4d", { lng: "en" }),
};

export function fieldLabel(field: string): string {
  return (
    FIELD_LABEL[field] ??
    field
      .replace(/([A-Z])/g, " $1")
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/^./, (c) => c.toUpperCase())
  );
}

function show(node: JourneyNode | undefined, field: string): string {
  if (!node) return "";
  switch (field) {
    case "dueBy":
      return node.dueBy ? formatShortDate(node.dueBy) : tr("copy.no_date_acb6273");
    case "status":
      return STATUS_LABEL[node.status];
    case "title":
      return node.title;
    default:
      return String((node as unknown as Record<string, unknown>)[field] ?? "");
  }
}

/** How one field of a step changes: "12 Nov" to "12 Dec". */
export function describeFieldChange(base: Journey, scenario: Journey, key: string, field: string): { field: string; from: string; to: string } {
  const before = base.nodes.find((n) => n.key === key);
  const after = scenario.nodes.find((n) => n.key === key);
  return { field: fieldLabel(field), from: show(before, field), to: show(after, field) };
}

/** Steps whose only change is their target date are grouped; they usually move together. */
export function splitChangedNodes(changes: NodeChange[]): { datesOnly: NodeChange[]; other: NodeChange[] } {
  const datesOnly = changes.filter((c) => c.fields.length === 1 && c.fields[0] === "dueBy");
  return { datesOnly, other: changes.filter((c) => !datesOnly.includes(c)) };
}

/** "7 days shorter", "3 days longer", "about the same". */
export function daysDelta(before: number, after: number): { text: string; direction: "shorter" | "longer" | "same" } {
  const delta = after - before;
  if (delta === 0) return { text: tr("copy.about_the_same_3964d77"), direction: "same" };
  const n = Math.abs(delta);
  return { text: `${n} ${n === 1 ? "day" : "days"} ${delta < 0 ? "shorter" : "longer"}`, direction: delta < 0 ? "shorter" : "longer" };
}
