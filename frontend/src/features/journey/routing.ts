/**
 * Orthogonal edge routing for the transit map. Pure.
 *
 * Stations never sit in the gaps between columns or in the padding between bands, so those
 * are free corridors. Every edge runs:
 *   - straight, when nothing stands between the two steps on that line;
 *   - with one bend in the gap before the dependent step, for neighbouring columns;
 *   - otherwise out into the gap after the prerequisite, along the band boundary closest to
 *     both ends, and down (or up) the gap before the dependent step.
 * So a line never passes behind a step it doesn't connect to. Edges into the same step share
 * one track in its gap (they read as a junction); other tracks are spread a few pixels apart.
 */
import type { Journey } from "@/domain/journey";
import { LAYOUT, columnX, type PlacedNode, type TransitLayout } from "./layout";

export interface Point {
  x: number;
  y: number;
}

export interface Route {
  points: Point[];
  /** Where an "either" label sits: on the first leg, next to the prerequisite. */
  label: Point;
  /** Vertical approval connector (pill below, step above). */
  vertical: boolean;
}

const TRACK = 7;
const CORRIDOR_TRACK = 6;
const CLEARANCE = 6;

/** Centre of the gap before a column. */
export function gapX(column: number): number {
  return columnX(column) - LAYOUT.columnGap / 2;
}

function spread(count: number, spacing: number, limit: number): (index: number) => number {
  const step = count > 1 ? Math.min(spacing, (limit * 2) / (count - 1)) : 0;
  return (index) => (index - (count - 1) / 2) * step;
}

function blocks(node: PlacedNode, y: number, fromColumn: number, toColumn: number): boolean {
  return node.column > fromColumn && node.column < toColumn && y > node.y - CLEARANCE && y < node.y + node.height + CLEARANCE;
}

export function routeEdges(journey: Journey, layout: TransitLayout): Map<string, Route> {
  const routes = new Map<string, Route>();
  const boundaries = [...layout.bands.map((b) => b.y), layout.height];

  interface Pending {
    id: string;
    from: PlacedNode;
    to: PlacedNode;
    sy: number;
    ty: number;
    kind: "straight" | "bend" | "corridor";
    corridor: number;
  }
  const pending: Pending[] = [];

  for (const edge of journey.edges) {
    const from = layout.byKey.get(edge.target); // prerequisite
    const to = layout.byKey.get(edge.source); // dependent
    if (!from || !to) continue;

    if (from.column === to.column) {
      // Approval under its step (or anything stacked in one cell): a short vertical connector.
      const x = to.x + to.width / 2;
      const [start, end] = from.y > to.y ? [from.y, to.y + to.height] : [from.y + from.height, to.y];
      routes.set(edge.id, { points: [{ x, y: start }, { x, y: end }], label: { x, y: (start + end) / 2 }, vertical: true });
      continue;
    }

    const sy = from.y + from.height / 2;
    const ty = to.y + to.height / 2;
    const [left, right] = from.column < to.column ? [from, to] : [to, from];
    const clear = !layout.nodes.some((n) => blocks(n, sy, left.column, right.column));
    let kind: Pending["kind"];
    if (Math.abs(to.column - from.column) === 1 || (clear && from.column < to.column)) kind = sy === ty && clear ? "straight" : "bend";
    else kind = "corridor";

    let corridor = 0;
    if (kind === "corridor") {
      const lo = Math.min(sy, ty);
      const hi = Math.max(sy, ty);
      const between = boundaries.filter((b) => b >= lo && b <= hi);
      const candidates = between.length ? between : boundaries;
      corridor = candidates.reduce((best, b) => (Math.abs(b - sy) + Math.abs(b - ty) < Math.abs(best - sy) + Math.abs(best - ty) ? b : best), candidates[0]!);
    }
    pending.push({ id: edge.id, from, to, sy, ty, kind, corridor });
  }

  // Tracks in each gap: one per dependent step (edges into it merge), one per prerequisite
  // leaving towards a corridor.
  const gapItems = new Map<number, Map<string, number>>();
  const addItem = (gap: number, item: string, y: number) => {
    const items = gapItems.get(gap) ?? new Map<string, number>();
    if (!items.has(item)) items.set(item, y);
    gapItems.set(gap, items);
  };
  for (const p of pending) {
    if (p.kind === "straight") continue;
    addItem(p.to.column, `in:${p.to.key}`, p.ty);
    if (p.kind === "corridor") addItem(p.from.column + 1, `out:${p.from.key}`, p.sy);
  }
  const trackX = new Map<string, number>();
  for (const [gap, items] of gapItems) {
    const ordered = [...items.entries()].sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]));
    const offset = spread(ordered.length, TRACK, LAYOUT.columnGap / 2 - 10);
    ordered.forEach(([item], index) => trackX.set(`${gap}|${item}`, gapX(gap) + offset(index)));
  }

  // Tracks along each corridor.
  const corridorEdges = new Map<number, Pending[]>();
  for (const p of pending) if (p.kind === "corridor") corridorEdges.set(p.corridor, [...(corridorEdges.get(p.corridor) ?? []), p]);
  const corridorY = new Map<string, number>();
  for (const [boundary, list] of corridorEdges) {
    const ordered = [...list].sort((a, b) => a.from.column - b.from.column || a.to.column - b.to.column || a.id.localeCompare(b.id));
    const offset = spread(ordered.length, CORRIDOR_TRACK, LAYOUT.bandPadTop - 8);
    ordered.forEach((p, index) => corridorY.set(p.id, boundary + offset(index)));
  }

  for (const p of pending) {
    const sx = p.from.x + p.from.width;
    const tx = p.to.x;
    const inX = trackX.get(`${p.to.column}|in:${p.to.key}`) ?? gapX(p.to.column);
    let points: Point[];
    if (p.kind === "straight") {
      points = [{ x: sx, y: p.sy }, { x: tx, y: p.ty }];
    } else if (p.kind === "bend") {
      points = [{ x: sx, y: p.sy }, { x: inX, y: p.sy }, { x: inX, y: p.ty }, { x: tx, y: p.ty }];
    } else {
      const outX = trackX.get(`${p.from.column + 1}|out:${p.from.key}`) ?? gapX(p.from.column + 1);
      const cy = corridorY.get(p.id) ?? p.corridor;
      points = [
        { x: sx, y: p.sy },
        { x: outX, y: p.sy },
        { x: outX, y: cy },
        { x: inX, y: cy },
        { x: inX, y: p.ty },
        { x: tx, y: p.ty },
      ];
    }
    const first = points[1] ?? points[0]!;
    routes.set(p.id, { points: simplify(points), label: { x: (sx + first.x) / 2, y: p.sy }, vertical: false });
  }
  return routes;
}

/** Drops repeated and collinear points. */
export function simplify(points: Point[]): Point[] {
  const unique = points.filter((p, i) => i === 0 || p.x !== points[i - 1]!.x || p.y !== points[i - 1]!.y);
  return unique.filter((p, i) => {
    if (i === 0 || i === unique.length - 1) return true;
    const a = unique[i - 1]!;
    const b = unique[i + 1]!;
    return !((a.x === p.x && p.x === b.x) || (a.y === p.y && p.y === b.y));
  });
}

/** SVG path through orthogonal points with rounded corners. */
export function roundedPath(points: Point[], radius = 12): string {
  if (points.length === 0) return "";
  const [start, ...rest] = points;
  let d = `M ${start!.x} ${start!.y}`;
  for (let i = 0; i < rest.length; i++) {
    const corner = rest[i]!;
    const next = rest[i + 1];
    if (!next) {
      d += ` L ${corner.x} ${corner.y}`;
      break;
    }
    const prev = i === 0 ? start! : rest[i - 1]!;
    const r = Math.min(radius, Math.hypot(corner.x - prev.x, corner.y - prev.y) / 2, Math.hypot(next.x - corner.x, next.y - corner.y) / 2);
    const inDir = { x: Math.sign(corner.x - prev.x), y: Math.sign(corner.y - prev.y) };
    const outDir = { x: Math.sign(next.x - corner.x), y: Math.sign(next.y - corner.y) };
    d += ` L ${corner.x - inDir.x * r} ${corner.y - inDir.y * r}`;
    d += ` Q ${corner.x} ${corner.y} ${corner.x + outDir.x * r} ${corner.y + outDir.y * r}`;
  }
  return d;
}
