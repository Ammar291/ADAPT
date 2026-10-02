import { tr } from "@/i18n";
/**
 * Compares two journeys: the current plan and a what-if scenario. Pure; used by mock
 * simulation and to enrich live results with titles.
 */
import type { Journey, JourneyNode } from "@/domain/journey";
import type { ScenarioDiff } from "@/domain/simulate";
import { criticalPathDays } from "./analysis";

const TASK_KINDS = new Set(["task", "appointment", "document", "requirement", "dependency", "action"]);
const COMPARED: (keyof JourneyNode)[] = ["status", "dueBy", "title", "kind"];

export function diffJourneys(
  base: Journey,
  scenario: Journey,
  changes: ScenarioDiff["changes"] = [],
  rerunStages: string[] = [],
): ScenarioDiff {
  const baseByKey = new Map(base.nodes.map((n) => [n.key, n]));
  const scenarioByKey = new Map(scenario.nodes.map((n) => [n.key, n]));
  const title = (key: string) => scenarioByKey.get(key)?.title ?? baseByKey.get(key)?.title ?? key;

  const addedTasks = scenario.nodes
    .filter((n) => !baseByKey.has(n.key) && TASK_KINDS.has(n.kind))
    .map((n) => ({ key: n.key, title: n.title, area: n.area }));
  const removedTasks = base.nodes
    .filter((n) => !scenarioByKey.has(n.key) && TASK_KINDS.has(n.kind))
    .map((n) => ({ key: n.key, title: n.title, area: n.area }));

  const changedNodes = scenario.nodes
    .filter((n) => baseByKey.has(n.key))
    .map((n) => {
      const before = baseByKey.get(n.key)!;
      const fields = COMPARED.filter((field) => before[field] !== n[field]).map(String);
      return { key: n.key, title: n.title, fields };
    })
    .filter((c) => c.fields.length > 0);

  const edgeKey = (e: { source: string; target: string; relation: string }) => `${e.source}|${e.target}|${e.relation}`;
  const baseEdges = new Map(base.edges.filter((e) => e.relation !== "approves").map((e) => [edgeKey(e), e]));
  const scenarioEdges = new Map(scenario.edges.filter((e) => e.relation !== "approves").map((e) => [edgeKey(e), e]));
  const changedDependencies = [
    ...[...scenarioEdges.entries()]
      .filter(([k]) => !baseEdges.has(k))
      .map(([, e]) => ({ source: e.source, target: e.target, relation: e.relation, change: "added" as const })),
    ...[...baseEdges.entries()]
      .filter(([k]) => !scenarioEdges.has(k))
      .map(([, e]) => ({ source: e.source, target: e.target, relation: e.relation, change: "removed" as const })),
  ].map((d) => ({ ...d, sourceTitle: title(d.source), targetTitle: title(d.target) }));

  const baseRisks = new Map(base.risks.map((r) => [r.id, r]));
  const scenarioRisks = new Map(scenario.risks.map((r) => [r.id, r]));
  const changedRisks = [
    ...scenario.risks
      .filter((r) => !baseRisks.has(r.id) || baseRisks.get(r.id)!.severity !== r.severity)
      .map((r) => ({ id: r.id, kind: r.kind, title: r.title, severity: r.severity, change: baseRisks.has(r.id) ? ("changed" as const) : ("added" as const) })),
    ...base.risks
      .filter((r) => !scenarioRisks.has(r.id))
      .map((r) => ({ id: r.id, kind: r.kind, title: r.title, severity: r.severity, change: "removed" as const })),
  ];

  const before = criticalPathDays(base);
  const after = criticalPathDays(scenario);
  const parts: string[] = [];
  if (addedTasks.length) parts.push(`${addedTasks.length} new ${addedTasks.length === 1 ? "step" : "steps"}`);
  if (removedTasks.length) parts.push(`${removedTasks.length} ${removedTasks.length === 1 ? "step" : "steps"} no longer needed`);
  if (changedDependencies.length) parts.push(`${changedDependencies.length} changed ${changedDependencies.length === 1 ? "dependency" : "dependencies"}`);
  const timing =
    after === before
      ? tr("copy.the_longest_chain_of_steps_stays_about_the_same_a984e29")
      : after > before
        ? `The longest chain of steps grows by about ${after - before} days.`
        : `The longest chain of steps shrinks by about ${before - after} days.`;
  const summary = parts.length ? `${capitalise(parts.join(", "))}. ${timing}` : `Nothing in your steps changes. ${timing}`;

  return { summary, changes, rerunStages, changedNodes, addedTasks, removedTasks, changedDependencies, changedRisks };
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
