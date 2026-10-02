/**
 * Radial layout for the private digital twin: the person at the centre, the people close to
 * them on the first ring, their own goals, documents, organisation and preferences on the
 * second, and the public rules the twin links to on the outer ring. Rings are ellipses shaped
 * like the viewport. Each outer node sits at the angle of the twin nodes it links to, so links
 * across the private/public boundary stay short and radial.
 */
import type { LayoutEdge, LayoutNode } from "./columns";
import { boundsOf, overlaps, packPositions, straightBetween, type EdgeRoute, type Rect } from "./geometry";

export type Ring = 0 | 1 | 2 | 3;

export interface RadialOptions {
  centerId: string;
  /** Ring for every node except the centre (1 people, 2 the person's own things, 3 public rules). */
  ring: (node: LayoutNode) => 1 | 2 | 3;
  size: (node: LayoutNode) => { width: number; height: number };
  /** Width / height of the viewport. */
  aspect: number;
  /** Order within the second ring (nodes of a kind stay together). */
  compare?: (a: LayoutNode, b: LayoutNode) => number;
  /** Corner radius of a node box, so straight edges meet the visible outline. */
  radius?: (node: LayoutNode) => number;
}

export interface RadialLayout {
  nodes: Map<string, Rect>;
  ringOf: Map<string, Ring>;
  /** Radii of each ring (index = ring). */
  rings: { rx: number; ry: number }[];
  edges: Map<string, EdgeRoute>;
  bounds: Rect;
}

const TAU = Math.PI * 2;
const TOP = -Math.PI / 2;

const normalise = (a: number) => ((a % TAU) + TAU) % TAU;

export function circularMean(angles: number[]): number | null {
  if (!angles.length) return null;
  const x = angles.reduce((s, a) => s + Math.cos(a), 0);
  const y = angles.reduce((s, a) => s + Math.sin(a), 0);
  if (Math.abs(x) < 1e-9 && Math.abs(y) < 1e-9) return angles[0]!;
  return Math.atan2(y, x);
}

/**
 * Spread angles around a circle, keeping their order, at least `sep` apart and as close as
 * possible to where each wants to be. The circle is cut at the widest gap between the wishes,
 * then packed as a line.
 */
export function spreadAngles(desired: number[], sep: number): number[] {
  const n = desired.length;
  if (n === 0) return [];
  if (n === 1) return [desired[0]!];
  const step = Math.min(sep, TAU / n);
  const order = desired.map((a, i) => ({ a: normalise(a), i })).sort((p, q) => p.a - q.a || p.i - q.i);
  let cut = 0;
  let widest = -1;
  order.forEach((p, j) => {
    const next = order[(j + 1) % n]!;
    const gap = j === n - 1 ? next.a + TAU - p.a : next.a - p.a;
    if (gap > widest) {
      widest = gap;
      cut = (j + 1) % n;
    }
  });
  const rotated = [...order.slice(cut), ...order.slice(0, cut)];
  const base = rotated[0]!.a;
  const line = rotated.map((p) => base + normalise(p.a - base));
  const packed = packPositions(line, step);
  const out = new Array<number>(n);
  rotated.forEach((p, j) => (out[p.i] = packed[j]!));
  return out;
}

export function radialLayout(nodes: LayoutNode[], edges: LayoutEdge[], options: RadialOptions): RadialLayout {
  const sizeOf = new Map(nodes.map((n) => [n.id, options.size(n)]));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ringOf = new Map<string, Ring>();
  for (const n of nodes) ringOf.set(n.id, n.id === options.centerId ? 0 : options.ring(n));
  const byLabel = (a: LayoutNode, b: LayoutNode) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id);
  const inRing = (r: Ring) => nodes.filter((n) => ringOf.get(n.id) === r);

  const ring1 = inRing(1).sort(byLabel);
  const ring2 = inRing(2).sort(options.compare ?? byLabel);
  const ring3 = inRing(3).sort(byLabel);

  const neighbours = new Map<string, string[]>();
  for (const e of edges) {
    if (!sizeOf.has(e.source) || !sizeOf.has(e.target) || e.source === e.target) continue;
    neighbours.set(e.source, [...(neighbours.get(e.source) ?? []), e.target]);
    neighbours.set(e.target, [...(neighbours.get(e.target) ?? []), e.source]);
  }

  // Ellipses follow a landscape viewport's shape, within reason. Never narrower than a circle:
  // wide pill-shaped nodes need room at the sides, so a tall ellipse only grows the map.
  const stretch = Math.min(1.7, Math.max(1, Math.sqrt(options.aspect)));
  const ratio = stretch * stretch; // rx / ry

  const angle = new Map<string, number>();
  const step2 = ring2.length ? TAU / ring2.length : TAU;
  ring2.forEach((n, i) => angle.set(n.id, TOP + step2 / 2 + i * step2));
  // People sit on the bisectors between second-ring nodes nearest the top, so spokes pass beside them.
  const step1 = Math.min(step2, TAU / Math.max(ring1.length, 1));
  ring1.forEach((n, i) => angle.set(n.id, TOP + (i - (ring1.length - 1) / 2) * step1 + (ring1.length % 2 === 0 ? step2 / 2 : 0)));

  const place = (id: string, a: number, rx: number, ry: number): Rect => {
    const size = sizeOf.get(id)!;
    return { x: rx * Math.cos(a) - size.width / 2, y: ry * Math.sin(a) - size.height / 2, width: size.width, height: size.height };
  };

  const rects = new Map<string, Rect>();
  const rings: { rx: number; ry: number }[] = [{ rx: 0, ry: 0 }];
  const placed: Rect[] = [];
  const center = byId.get(options.centerId);
  if (center) {
    const r = place(center.id, 0, 0, 0);
    rects.set(center.id, r);
    placed.push(r);
  }
  const extent = (list: LayoutNode[]) => ({
    w: Math.max(0, ...list.map((n) => sizeOf.get(n.id)!.width)),
    h: Math.max(0, ...list.map((n) => sizeOf.get(n.id)!.height)),
  });

  let inner = rings[0]!;
  let innerSize = center ? extent([center]) : { w: 0, h: 0 };
  const layRing = (list: LayoutNode[], index: 1 | 2 | 3, angles: (rx: number, ry: number) => number[]) => {
    if (!list.length) {
      rings[index] = inner;
      return;
    }
    const size = extent(list);
    let ry = Math.max(inner.ry + (innerSize.h + size.h) / 2 + 40, (inner.rx + (innerSize.w + size.w) / 2 + 36) / ratio);
    let rx = ry * ratio;
    let as = angles(rx, ry);
    let candidate = list.map((n, i) => place(n.id, as[i]!, rx, ry));
    for (let attempt = 0; attempt < 80; attempt++) {
      const clash =
        candidate.some((r, i) => candidate.some((o, j) => j > i && overlaps(r, o, 16))) || candidate.some((r) => placed.some((o) => overlaps(r, o, 20)));
      if (!clash) break;
      ry *= 1.06;
      rx *= 1.06;
      as = angles(rx, ry);
      candidate = list.map((n, i) => place(n.id, as[i]!, rx, ry));
    }
    list.forEach((n, i) => {
      rects.set(n.id, candidate[i]!);
      angle.set(n.id, as[i]!);
    });
    placed.push(...candidate);
    rings[index] = { rx, ry };
    inner = { rx, ry };
    innerSize = size;
  };

  layRing(ring1, 1, () => ring1.map((n) => angle.get(n.id)!));
  layRing(ring2, 2, () => ring2.map((n) => angle.get(n.id)!));
  const wishes = ring3.map((n) => {
    const linked = (neighbours.get(n.id) ?? []).map((id) => (ringOf.get(id) === 3 ? undefined : angle.get(id))).filter((a): a is number => a !== undefined);
    return circularMean(linked) ?? TOP;
  });
  const size3 = extent(ring3);
  layRing(ring3, 3, (rx, ry) => spreadAngles(wishes, Math.max((size3.w + 18) / rx, (size3.h + 18) / ry)));

  const routes = new Map<string, EdgeRoute>();
  for (const e of edges) {
    const s = rects.get(e.source);
    const t = rects.get(e.target);
    if (!s || !t || e.source === e.target) continue;
    routes.set(e.id, straightBetween(s, t, options.radius?.(byId.get(e.source)!) ?? 0));
  }

  return { nodes: rects, ringOf, rings, edges: routes, bounds: boundsOf(rects.values()) };
}
