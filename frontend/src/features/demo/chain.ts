/**
 * Layout of a plan as a dependency chain: one column per dependency depth (what can start
 * now on the left, what waits longest on the right) and one band per area of life. Pure,
 * so it is tested without a browser. Edges run from a prerequisite to what waits for it.
 */
import type { LifeArea } from "@/domain/common";
import type { Journey, JourneyNode } from "@/domain/journey";
import type { ScenarioRoleRef } from "@/domain/scenario";

export const LANE_ORDER: LifeArea[] = ["business", "residency", "health", "family", "housing", "finance", "daily_life", "community"];

export const SIZE = {
  column: 152,
  gap: 26,
  node: 40,
  featured: 60,
  stack: 8,
  lanePad: 12,
  label: 104,
} as const;

export interface ChainNode {
  key: string;
  node: JourneyNode;
  depth: number;
  area: LifeArea;
  roles: ScenarioRoleRef[];
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ChainEdge {
  /** `dependent<-prerequisite`, the same id the what-if diff uses. */
  id: string;
  from: string;
  to: string;
  path: string;
}

export interface ChainLane {
  area: LifeArea;
  y: number;
  h: number;
}

export interface ChainLayout {
  nodes: ChainNode[];
  edges: ChainEdge[];
  lanes: ChainLane[];
  width: number;
  height: number;
}

/** Longest path from a step with no prerequisites. Edges: source waits for target. */
export function depths(journey: Pick<Journey, "nodes" | "edges">): Map<string, number> {
  const prerequisites = new Map<string, string[]>();
  for (const node of journey.nodes) prerequisites.set(node.key, []);
  for (const edge of journey.edges) prerequisites.get(edge.source)?.push(edge.target);
  const memo = new Map<string, number>();
  const visit = (key: string, path: Set<string>): number => {
    const known = memo.get(key);
    if (known !== undefined) return known;
    if (path.has(key)) return 0; // a cycle: the planner reports it; draw it flat
    path.add(key);
    const before = (prerequisites.get(key) ?? []).filter((k) => prerequisites.has(k));
    const depth = before.length ? 1 + Math.max(...before.map((k) => visit(k, path))) : 0;
    path.delete(key);
    memo.set(key, depth);
    return depth;
  };
  for (const node of journey.nodes) visit(node.key, new Set());
  return memo;
}

export function layoutChain(journey: Pick<Journey, "nodes" | "edges">, roles: ScenarioRoleRef[] = []): ChainLayout {
  const depth = depths(journey);
  const rolesOf = (key: string) => roles.filter((r) => r.nodeKey === key && r.role !== "missing_information");
  const areas = LANE_ORDER.filter((area) => journey.nodes.some((n) => n.area === area));
  for (const node of journey.nodes) if (!areas.includes(node.area)) areas.push(node.area);

  const nodes: ChainNode[] = [];
  const lanes: ChainLane[] = [];
  let y = 0;
  for (const area of areas) {
    const inLane = journey.nodes.filter((n) => n.area === area);
    const columns = new Map<number, JourneyNode[]>();
    for (const node of inLane) {
      const d = depth.get(node.key) ?? 0;
      columns.set(d, [...(columns.get(d) ?? []), node]);
    }
    let laneHeight = 0;
    for (const [d, members] of columns) {
      members.sort((a, b) => rolesOf(b.key).length - rolesOf(a.key).length || a.title.localeCompare(b.title));
      let offset = SIZE.lanePad;
      for (const node of members) {
        const h = rolesOf(node.key).length ? SIZE.featured : SIZE.node;
        nodes.push({
          key: node.key,
          node,
          depth: d,
          area,
          roles: rolesOf(node.key),
          x: SIZE.label + d * (SIZE.column + SIZE.gap),
          y: y + offset,
          w: SIZE.column,
          h,
        });
        offset += h + SIZE.stack;
      }
      laneHeight = Math.max(laneHeight, offset - SIZE.stack + SIZE.lanePad);
    }
    lanes.push({ area, y, h: laneHeight });
    y += laneHeight;
  }

  const at = new Map(nodes.map((n) => [n.key, n]));
  const edges: ChainEdge[] = [];
  for (const edge of journey.edges) {
    const dependent = at.get(edge.source);
    const prerequisite = at.get(edge.target);
    if (!dependent || !prerequisite) continue;
    const x1 = prerequisite.x + prerequisite.w;
    const y1 = prerequisite.y + prerequisite.h / 2;
    const x2 = dependent.x;
    const y2 = dependent.y + dependent.h / 2;
    const bend = Math.max(24, (x2 - x1) / 2);
    edges.push({
      id: `${edge.source}<-${edge.target}`,
      from: edge.target,
      to: edge.source,
      path: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
    });
  }
  const columns = Math.max(0, ...nodes.map((n) => n.depth)) + 1;
  return { nodes, edges, lanes, width: SIZE.label + columns * (SIZE.column + SIZE.gap), height: y };
}

/** A step and everything it waits for or unlocks (its whole chain). */
export function chainOf(journey: Pick<Journey, "edges">, key: string): Set<string> {
  const seen = new Set<string>([key]);
  const walk = (start: string, next: (k: string) => string[]) => {
    const queue = [start];
    while (queue.length) {
      for (const k of next(queue.shift()!)) {
        if (!seen.has(k)) {
          seen.add(k);
          queue.push(k);
        }
      }
    }
  };
  walk(key, (k) => journey.edges.filter((e) => e.source === k).map((e) => e.target));
  walk(key, (k) => journey.edges.filter((e) => e.target === k).map((e) => e.source));
  return seen;
}

/** What a what-if removed from the base plan: steps and `dependent<-prerequisite` edges. */
export function removedBy(base: Pick<Journey, "nodes" | "edges">, scenario: Pick<Journey, "nodes" | "edges">): { nodes: Set<string>; edges: Set<string> } {
  const keep = new Set(scenario.nodes.map((n) => n.key));
  const kept = new Set(scenario.edges.map((e) => `${e.source}<-${e.target}`));
  return {
    nodes: new Set(base.nodes.filter((n) => !keep.has(n.key)).map((n) => n.key)),
    edges: new Set(base.edges.map((e) => `${e.source}<-${e.target}`).filter((id) => !kept.has(id))),
  };
}
