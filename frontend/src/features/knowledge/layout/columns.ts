/**
 * Column layout for the public governance graph: one column (zone) per kind of entity, left to
 * right, with the hub column (services) in the middle. Tall zones wrap into sub-columns so the
 * whole map keeps roughly the shape of the viewport.
 *
 *   1. The hub is ordered so dependency chains sit next to each other and services that share a
 *      document, channel or authority stay close (local search over a simple cost).
 *   2. Every other node is placed at the height of the hub nodes it connects to (barycentre),
 *      then packed so nothing overlaps. Ordering by barycentre is what keeps crossings down.
 *   3. Edges are routed between facing sides of the boxes.
 */
import { centerOf, packPositions, routeBetween, type EdgeRoute, type Rect } from "./geometry";

export interface LayoutNode {
  id: string;
  type: string;
  label: string;
}

export interface LayoutEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
}

export interface ColumnSpec {
  id: string;
  title: string;
  types: readonly string[];
  /** Node box size in this column. */
  width: number;
  height: number;
  /** The column everything else is arranged around. */
  hub?: boolean;
  /** Receives node types no column lists. Defaults to the hub. */
  fallback?: boolean;
}

export interface ColumnLayoutOptions {
  columns: readonly ColumnSpec[];
  /** Width / height of the viewport the map should fill. */
  aspect: number;
  rowGap?: number;
  subColumnGap?: number;
  columnGap?: number;
  headerHeight?: number;
}

export interface LaidOutColumn {
  id: string;
  title: string;
  count: number;
  /** The column heading's box, above the column. */
  header: Rect;
  subColumns: number;
}

export interface ColumnLayout {
  nodes: Map<string, Rect>;
  columnOf: Map<string, string>;
  columns: LaidOutColumn[];
  edges: Map<string, EdgeRoute>;
  bounds: Rect;
}

const byLabel = (a: LayoutNode, b: LayoutNode) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id);

/** How many rows per sub-column give the map the best fit (largest zoom) for the viewport shape. */
export function chooseRows(
  counts: number[],
  columns: readonly Pick<ColumnSpec, "width" | "height">[],
  aspect: number,
  gaps: { row: number; sub: number; column: number; header: number },
): number {
  const max = Math.max(1, ...counts);
  let best = max;
  let bestScore = -Infinity;
  for (let rows = 1; rows <= max; rows++) {
    let width = 0;
    let height = 0;
    let used = 0;
    counts.forEach((count, i) => {
      if (!count) return;
      const col = columns[i]!;
      const subs = Math.ceil(count / rows);
      width += subs * col.width + (subs - 1) * gaps.sub;
      height = Math.max(height, Math.ceil(count / subs) * (col.height + gaps.row) - gaps.row);
      used++;
    });
    width += Math.max(0, used - 1) * gaps.column;
    height += gaps.header;
    const score = Math.min(aspect / width, 1 / height);
    if (score > bestScore + 1e-12) {
      bestScore = score;
      best = rows;
    }
  }
  return best;
}

interface HubModel {
  /** Pairs of hub positions joined by an edge inside the hub. */
  intra: [number, number][];
  /** Groups of hub positions that share a neighbour outside the hub, with a weight. */
  groups: { members: number[]; weight: number }[];
}

function hubCost(order: number[], subs: number, model: HubModel): number {
  const slot = new Array<number>(order.length);
  order.forEach((node, i) => (slot[node] = i));
  let cost = 0;
  for (const [a, b] of model.intra) {
    const ia = slot[a]!;
    const ib = slot[b]!;
    const rowGap = Math.abs(Math.floor(ia / subs) - Math.floor(ib / subs));
    const subGap = Math.abs((ia % subs) - (ib % subs));
    cost += rowGap * 2 + subGap + (subGap === 0 && rowGap > 1 ? 3 : 0);
  }
  for (const group of model.groups) {
    let lo = Infinity;
    let hi = -Infinity;
    for (const m of group.members) {
      const row = Math.floor(slot[m]! / subs);
      lo = Math.min(lo, row);
      hi = Math.max(hi, row);
    }
    cost += (hi - lo) * group.weight;
  }
  return cost;
}

/**
 * Order the hub: a depth-first pass puts each node's prerequisites (edge targets) just before
 * it, then single-node moves improve the cost until nothing does.
 */
export function orderHub(hub: LayoutNode[], edges: LayoutEdge[], outsideNeighbours: Map<string, string[]>, subs: number): string[] {
  const sorted = [...hub].sort(byLabel);
  const index = new Map(sorted.map((n, i) => [n.id, i]));
  const targets = new Map<number, number[]>();
  const hasDependents = new Set<number>();
  const intra: [number, number][] = [];
  for (const e of edges) {
    const s = index.get(e.source);
    const t = index.get(e.target);
    if (s === undefined || t === undefined || s === t) continue;
    intra.push([s, t]);
    targets.set(s, [...(targets.get(s) ?? []), t]);
    hasDependents.add(t);
  }

  const visited = new Set<number>();
  const initial: number[] = [];
  const visit = (i: number) => {
    if (visited.has(i)) return;
    visited.add(i);
    for (const t of [...(targets.get(i) ?? [])].sort((a, b) => a - b)) visit(t);
    initial.push(i);
  };
  // Start from what nothing else depends on (the end of each chain), then anything left in cycles.
  sorted.forEach((_, i) => !hasDependents.has(i) && visit(i));
  sorted.forEach((_, i) => visit(i));

  const groups: HubModel["groups"] = [];
  for (const members of outsideNeighbours.values()) {
    const positions = [...new Set(members.map((id) => index.get(id)).filter((i): i is number => i !== undefined))];
    if (positions.length > 1) groups.push({ members: positions, weight: 1 / (positions.length - 1) });
  }
  const model: HubModel = { intra, groups };

  let order = initial;
  let cost = hubCost(order, subs, model);
  for (let pass = 0; pass < 40; pass++) {
    let improved = false;
    for (let from = 0; from < order.length; from++) {
      const node = order[from]!;
      const without = order.filter((_, i) => i !== from);
      let bestOrder: number[] | null = null;
      let bestCost = cost;
      for (let to = 0; to <= without.length; to++) {
        if (to === from) continue;
        const candidate = [...without.slice(0, to), node, ...without.slice(to)];
        const c = hubCost(candidate, subs, model);
        if (c < bestCost - 1e-9) {
          bestCost = c;
          bestOrder = candidate;
        }
      }
      if (bestOrder) {
        order = bestOrder;
        cost = bestCost;
        improved = true;
      }
    }
    if (!improved) break;
  }
  return order.map((i) => sorted[i]!.id);
}

export function columnLayout(nodes: LayoutNode[], edges: LayoutEdge[], options: ColumnLayoutOptions): ColumnLayout {
  const rowGap = options.rowGap ?? 14;
  const subGap = options.subColumnGap ?? 28;
  const colGap = options.columnGap ?? 120;
  const headerHeight = options.headerHeight ?? 64;
  const specs = options.columns;

  const typeColumn = new Map<string, number>();
  specs.forEach((c, i) => c.types.forEach((t) => typeColumn.set(t, i)));
  let hubIndex = specs.findIndex((c) => c.hub);
  if (hubIndex < 0) hubIndex = 0;
  const fallbackIndex = specs.findIndex((c) => c.fallback);
  const fallback = fallbackIndex >= 0 ? fallbackIndex : hubIndex;

  const members: LayoutNode[][] = specs.map(() => []);
  const columnIndexOf = new Map<string, number>();
  for (const node of [...nodes].sort(byLabel)) {
    const ci = typeColumn.get(node.type) ?? fallback;
    members[ci]!.push(node);
    columnIndexOf.set(node.id, ci);
  }

  const valid = edges.filter((e) => e.source !== e.target && columnIndexOf.has(e.source) && columnIndexOf.has(e.target));
  const neighbours = new Map<string, string[]>();
  for (const e of valid) {
    neighbours.set(e.source, [...(neighbours.get(e.source) ?? []), e.target]);
    neighbours.set(e.target, [...(neighbours.get(e.target) ?? []), e.source]);
  }

  const counts = members.map((m) => m.length);
  const rows = chooseRows(counts, specs, options.aspect, { row: rowGap, sub: subGap, column: colGap, header: headerHeight });
  const subs = counts.map((n) => Math.max(1, Math.ceil(n / rows)));
  const pitch = specs.map((c) => c.height + rowGap);
  const bodyHeight = Math.max(...counts.map((n, i) => (n ? Math.ceil(n / subs[i]!) * pitch[i]! - rowGap : 0)), 0);

  // Column x positions (empty columns take no room).
  const columnX: number[] = [];
  let x = 0;
  specs.forEach((c, i) => {
    columnX[i] = x;
    if (counts[i]) x += subs[i]! * c.width + (subs[i]! - 1) * subGap + colGap;
  });
  const zoneWidth = (i: number) => subs[i]! * specs[i]!.width + (subs[i]! - 1) * subGap;
  const slotX = (ci: number, sub: number) => columnX[ci]! + sub * (specs[ci]!.width + subGap);

  const rects = new Map<string, Rect>();
  const subOf = new Map<string, number>();

  // 1. Hub.
  const hubMembers = members[hubIndex]!;
  const hubIds = new Set(hubMembers.map((n) => n.id));
  const outside = new Map<string, string[]>();
  for (const e of valid) {
    const sIn = hubIds.has(e.source);
    const tIn = hubIds.has(e.target);
    if (sIn === tIn) continue;
    const other = sIn ? e.target : e.source;
    outside.set(other, [...(outside.get(other) ?? []), sIn ? e.source : e.target]);
  }
  const hubSpec = specs[hubIndex]!;
  const hubSubs = subs[hubIndex]!;
  const hubOrder = orderHub(hubMembers, valid.filter((e) => hubIds.has(e.source) && hubIds.has(e.target)), outside, hubSubs);
  const hubRows = Math.ceil(hubOrder.length / hubSubs);
  const hubTop = headerHeight + (bodyHeight - (hubRows * pitch[hubIndex]! - rowGap)) / 2;
  hubOrder.forEach((id, i) => {
    const sub = i % hubSubs;
    rects.set(id, { x: slotX(hubIndex, sub), y: hubTop + Math.floor(i / hubSubs) * pitch[hubIndex]!, width: hubSpec.width, height: hubSpec.height });
    subOf.set(id, sub);
  });

  // 2. Other columns, nearest to the hub first so each can lean on the ones already placed.
  const rest = specs.map((_, i) => i).filter((i) => i !== hubIndex && counts[i]);
  rest.sort((a, b) => Math.abs(a - hubIndex) - Math.abs(b - hubIndex) || a - b);
  for (const ci of rest) {
    const spec = specs[ci]!;
    const k = subs[ci]!;
    const desired = new Map<string, number>();
    for (const node of members[ci]!) {
      const ys = (neighbours.get(node.id) ?? []).map((id) => rects.get(id)).filter((r): r is Rect => Boolean(r)).map((r) => centerOf(r).y);
      if (ys.length) desired.set(node.id, ys.reduce((a, b) => a + b, 0) / ys.length);
    }
    const fallbackY = headerHeight + bodyHeight;
    const ordered = [...members[ci]!].sort((a, b) => (desired.get(a.id) ?? fallbackY) - (desired.get(b.id) ?? fallbackY) || byLabel(a, b));
    const rowGroups: LayoutNode[][] = [];
    for (let i = 0; i < ordered.length; i += k) rowGroups.push(ordered.slice(i, i + k));
    const rowDesired = rowGroups.map((group) => group.reduce((sum, n) => sum + (desired.get(n.id) ?? fallbackY), 0) / group.length - spec.height / 2);
    const tops = packPositions(rowDesired, pitch[ci]!, headerHeight, headerHeight + bodyHeight - spec.height);
    // Within a row, the node with most links to the hub takes the sub-column nearest the hub.
    const hubward = ci < hubIndex;
    rowGroups.forEach((group, r) => {
      const byHubLinks = [...group].sort(
        (a, b) =>
          (neighbours.get(b.id) ?? []).filter((id) => hubIds.has(id)).length - (neighbours.get(a.id) ?? []).filter((id) => hubIds.has(id)).length ||
          byLabel(a, b),
      );
      byHubLinks.forEach((node, j) => {
        const sub = hubward ? k - 1 - j : j;
        rects.set(node.id, { x: slotX(ci, sub), y: tops[r]!, width: spec.width, height: spec.height });
        subOf.set(node.id, sub);
      });
    });
  }

  // 3. Edges.
  const routes = new Map<string, EdgeRoute>();
  for (const e of valid) {
    const s = rects.get(e.source)!;
    const t = rects.get(e.target)!;
    const ci = columnIndexOf.get(e.source)!;
    const side = subs[ci]! > 1 && subOf.get(e.source) === 0 ? "left" : "right";
    routes.set(e.id, routeBetween(s, t, { side, gap: rowGap }));
  }

  const columns: LaidOutColumn[] = specs
    .map((spec, i) => ({
      id: spec.id,
      title: spec.title,
      count: counts[i]!,
      header: { x: columnX[i]!, y: 0, width: zoneWidth(i), height: headerHeight - 24 },
      subColumns: subs[i]!,
    }))
    .filter((c) => c.count > 0);

  const columnOf = new Map<string, string>();
  columnIndexOf.forEach((ci, id) => columnOf.set(id, specs[ci]!.id));

  const width = Math.max(0, x - colGap);
  return { nodes: rects, columnOf, columns, edges: routes, bounds: { x: 0, y: 0, width, height: headerHeight + bodyHeight } };
}
