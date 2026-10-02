import { tr } from "@/i18n";
/**
 * Pure journey analysis shared by Home, Journey, Simulate and the assistant. No I/O.
 */
import type { Journey, JourneyEdge, JourneyNode, JourneyNodeStatus } from "@/domain/journey";

export type JourneyFilter = "all" | "todo" | "blocked" | "prepared" | "waiting_for_me" | "done";

export const JOURNEY_FILTERS: { id: JourneyFilter; label: string }[] = [
  { id: "all", label: tr("copy.all_6a72085", { lng: "en" }) },
  { id: "todo", label: tr("copy.to_do_8665aed", { lng: "en" }) },
  { id: "blocked", label: tr("copy.blocked_99613c7", { lng: "en" }) },
  { id: "prepared", label: tr("copy.prepared_d8b21a6", { lng: "en" }) },
  { id: "waiting_for_me", label: tr("copy.waiting_for_me_a545ea1", { lng: "en" }) },
  { id: "done", label: tr("copy.completed_1798b3b", { lng: "en" }) },
];

export const STATUS_LABEL: Record<JourneyNodeStatus, string> = {
  todo: tr("copy.to_do_8665aed", { lng: "en" }),
  in_progress: tr("copy.in_progress_b6bd42e", { lng: "en" }),
  blocked: tr("copy.blocked_99613c7", { lng: "en" }),
  prepared: tr("copy.prepared_d8b21a6", { lng: "en" }),
  waiting_for_me: tr("copy.needs_user_action_238e46e", { lng: "en" }),
  done: tr("copy.completed_1798b3b", { lng: "en" }),
  not_applicable: tr("copy.not_needed_2518be9", { lng: "en" }),
};

export function filterOf(status: JourneyNodeStatus): JourneyFilter | null {
  switch (status) {
    case "todo":
    case "in_progress":
      return "todo";
    case "blocked":
      return "blocked";
    case "prepared":
      return "prepared";
    case "waiting_for_me":
      return "waiting_for_me";
    case "done":
      return "done";
    default:
      return null;
  }
}

export function matchesFilter(node: JourneyNode, filter: JourneyFilter): boolean {
  return filter === "all" ? node.status !== "not_applicable" : filterOf(node.status) === filter;
}

export function countByFilter(journey: Journey): Record<JourneyFilter, number> {
  const counts: Record<JourneyFilter, number> = { all: 0, todo: 0, blocked: 0, prepared: 0, waiting_for_me: 0, done: 0 };
  for (const node of journey.nodes) {
    if (node.status === "not_applicable") continue;
    counts.all += 1;
    const f = filterOf(node.status);
    if (f) counts[f] += 1;
  }
  return counts;
}

/** Share of the plan that's done. Approval checkpoints and external dependencies don't count. */
export function completion(journey: Journey): { done: number; total: number; percent: number } {
  const counted = journey.nodes.filter(
    (n) => n.status !== "not_applicable" && n.kind !== "approval" && n.kind !== "dependency",
  );
  const done = counted.filter((n) => n.status === "done").length;
  return { done, total: counted.length, percent: counted.length ? Math.round((done / counted.length) * 100) : 0 };
}

export function nodeByKey(journey: Journey, key: string): JourneyNode | undefined {
  return journey.nodes.find((n) => n.key === key);
}

const BLOCKING: JourneyEdge["relation"][] = ["depends_on", "requires", "blocked_by"];

/** What must happen before this node. */
export function prerequisites(journey: Journey, key: string): { node: JourneyNode; edge: JourneyEdge }[] {
  return journey.edges
    .filter((e) => e.source === key && BLOCKING.includes(e.relation))
    .map((edge) => ({ edge, node: nodeByKey(journey, edge.target)! }))
    .filter((p) => p.node);
}

/** What this node unlocks. */
export function unlocks(journey: Journey, key: string): JourneyNode[] {
  return journey.edges
    .filter((e) => e.target === key && BLOCKING.includes(e.relation))
    .map((e) => nodeByKey(journey, e.source)!)
    .filter(Boolean);
}

/** Everything downstream of a node (transitively), for "delaying this delays…" copy. */
export function downstream(journey: Journey, key: string): Set<string> {
  const seen = new Set<string>();
  const queue = [key];
  while (queue.length) {
    const current = queue.shift()!;
    for (const next of unlocks(journey, current)) {
      if (!seen.has(next.key)) {
        seen.add(next.key);
        queue.push(next.key);
      }
    }
  }
  return seen;
}

/**
 * The chain of unfinished steps with the longest total estimated duration: the critical
 * path. Delaying any of them delays the whole plan.
 */
export function criticalPath(journey: Journey): string[] {
  const open = new Map(journey.nodes.filter((n) => n.status !== "done" && n.status !== "not_applicable").map((n) => [n.key, n]));
  const memo = new Map<string, { length: number; path: string[] }>();
  const visit = (key: string, stack: Set<string>): { length: number; path: string[] } => {
    const cached = memo.get(key);
    if (cached) return cached;
    if (stack.has(key)) return { length: 0, path: [] };
    stack.add(key);
    const node = open.get(key)!;
    let best = { length: 0, path: [] as string[] };
    for (const { node: pre } of prerequisites(journey, key)) {
      if (!open.has(pre.key)) continue;
      const candidate = visit(pre.key, stack);
      if (candidate.length > best.length) best = candidate;
    }
    stack.delete(key);
    const result = { length: best.length + (node.estimatedDays ?? 0), path: [...best.path, key] };
    memo.set(key, result);
    return result;
  };
  let best = { length: 0, path: [] as string[] };
  for (const key of open.keys()) {
    const candidate = visit(key, new Set());
    if (candidate.length > best.length) best = candidate;
  }
  return best.path;
}

/** Total estimated days along the critical path (ADAPT estimate). */
export function criticalPathDays(journey: Journey): number {
  return criticalPath(journey).reduce((sum, key) => sum + (nodeByKey(journey, key)?.estimatedDays ?? 0), 0);
}

const PRIORITY: Partial<Record<JourneyNodeStatus, number>> = {
  waiting_for_me: 0,
  prepared: 1,
  in_progress: 2,
  todo: 3,
};

/**
 * What the user can do now, most useful first: things waiting on them, then prepared
 * handoffs, then work in progress. Critical-path items and earlier due dates win ties.
 */
export function nextActions(journey: Journey, limit = 5): JourneyNode[] {
  const critical = new Set(criticalPath(journey));
  return journey.nodes
    .filter((n) => PRIORITY[n.status] !== undefined && n.kind !== "dependency" && n.action)
    .sort((a, b) => {
      const p = PRIORITY[a.status]! - PRIORITY[b.status]!;
      if (p !== 0) return p;
      const c = Number(critical.has(b.key)) - Number(critical.has(a.key));
      if (c !== 0) return c;
      return (a.dueBy ?? "9999").localeCompare(b.dueBy ?? "9999");
    })
    .slice(0, limit);
}

/** Blocked nodes with what's blocking them, most consequential (most downstream) first. */
export function blockedNodes(journey: Journey): JourneyNode[] {
  return journey.nodes
    .filter((n) => n.status === "blocked")
    .sort((a, b) => downstream(journey, b.key).size - downstream(journey, a.key).size);
}

/** Upcoming appointments and approvals, soonest first. */
export function upcoming(journey: Journey): JourneyNode[] {
  return journey.nodes
    .filter((n) => (n.kind === "appointment" || n.kind === "approval") && n.status !== "done" && n.status !== "not_applicable")
    .sort((a, b) => Number(b.status === "waiting_for_me") - Number(a.status === "waiting_for_me") || (a.dueBy ?? "9999").localeCompare(b.dueBy ?? "9999"));
}

/** Longest-path depth of each node over blocking edges (0 = can start now). */
export function depthOf(journey: Journey): Map<string, number> {
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const visit = (key: string): number => {
    const known = depth.get(key);
    if (known !== undefined) return known;
    if (visiting.has(key)) return 0;
    visiting.add(key);
    const pres = prerequisites(journey, key);
    const value = pres.length ? Math.max(...pres.map((p) => visit(p.node.key))) + 1 : 0;
    visiting.delete(key);
    depth.set(key, value);
    return value;
  };
  journey.nodes.forEach((n) => visit(n.key));
  return depth;
}
