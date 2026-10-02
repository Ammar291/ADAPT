/**
 * Geometry shared by the graph layouts: rectangles, 1D packing and edge paths.
 * Pure functions; coordinates are React Flow canvas units (top-left origin).
 */

export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface EdgeRoute {
  /** SVG path data. */
  path: string;
  /** Where a label for the edge sits (roughly the middle of the path). */
  label: Point;
}

export function centerOf(r: Rect): Point {
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}

export function overlaps(a: Rect, b: Rect, margin = 0): boolean {
  return a.x < b.x + b.width + margin && b.x < a.x + a.width + margin && a.y < b.y + b.height + margin && b.y < a.y + a.height + margin;
}

export function boundsOf(rects: Iterable<Rect>): Rect {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const r of rects) {
    minX = Math.min(minX, r.x);
    minY = Math.min(minY, r.y);
    maxX = Math.max(maxX, r.x + r.width);
    maxY = Math.max(maxY, r.y + r.height);
  }
  if (minX === Infinity) return { x: 0, y: 0, width: 0, height: 0 };
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

/**
 * Positions for items kept in the given order, at least `gap` apart, as close as possible
 * (least squares) to where each wants to be, within [min, max]. This is isotonic regression
 * on shifted targets (pool adjacent violators), then clamped to the bounds, which is exact
 * for a uniform box constraint.
 */
export function packPositions(desired: number[], gap: number, min = -Infinity, max = Infinity): number[] {
  const n = desired.length;
  if (!n) return [];
  const blocks: { sum: number; count: number }[] = [];
  desired.forEach((d, i) => {
    blocks.push({ sum: d - i * gap, count: 1 });
    while (blocks.length > 1) {
      const last = blocks[blocks.length - 1]!;
      const prev = blocks[blocks.length - 2]!;
      if (prev.sum / prev.count <= last.sum / last.count) break;
      prev.sum += last.sum;
      prev.count += last.count;
      blocks.pop();
    }
  });
  const upper = Math.max(min, max - (n - 1) * gap);
  const out: number[] = [];
  for (const block of blocks) {
    const z = Math.min(upper, Math.max(min, block.sum / block.count));
    for (let i = 0; i < block.count; i++) out.push(z + out.length * gap);
  }
  return out;
}

const round = (v: number) => Math.round(v * 10) / 10;

function cubicPoint(p0: Point, c1: Point, c2: Point, p1: Point, t: number): Point {
  const u = 1 - t;
  return {
    x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
    y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y,
  };
}

function cubic(p0: Point, c1: Point, c2: Point, p1: Point): EdgeRoute {
  return {
    path: `M${round(p0.x)},${round(p0.y)} C${round(c1.x)},${round(c1.y)} ${round(c2.x)},${round(c2.y)} ${round(p1.x)},${round(p1.y)}`,
    label: cubicPoint(p0, c1, c2, p1, 0.5),
  };
}

/**
 * Route an edge between two node boxes laid out in columns:
 *   - boxes side by side: a horizontal S-curve between the facing sides;
 *   - boxes stacked and adjacent: a short vertical connector;
 *   - boxes in the same column further apart: an arc that bulges out on `side`, so it never
 *     runs through the boxes in between.
 */
export function routeBetween(s: Rect, t: Rect, options: { side?: "left" | "right"; gap?: number } = {}): EdgeRoute {
  const sc = centerOf(s);
  const tc = centerOf(t);
  if (t.x >= s.x + s.width - 0.5 || t.x + t.width <= s.x + 0.5) {
    const rightward = t.x >= s.x + s.width - 0.5;
    const p0 = { x: rightward ? s.x + s.width : s.x, y: sc.y };
    const p1 = { x: rightward ? t.x : t.x + t.width, y: tc.y };
    const dx = Math.max(18, Math.abs(p1.x - p0.x) * 0.5) * (rightward ? 1 : -1);
    return cubic(p0, { x: p0.x + dx, y: p0.y }, { x: p1.x - dx, y: p1.y }, p1);
  }
  const gap = options.gap ?? 16;
  const below = tc.y > sc.y;
  const between = below ? t.y - (s.y + s.height) : s.y - (t.y + t.height);
  if (between >= 0 && between <= gap * 1.6) {
    const p0 = { x: sc.x, y: below ? s.y + s.height : s.y };
    const p1 = { x: tc.x, y: below ? t.y : t.y + t.height };
    const dy = (p1.y - p0.y) / 2;
    return cubic(p0, { x: p0.x, y: p0.y + dy }, { x: p1.x, y: p1.y - dy }, p1);
  }
  const side = options.side ?? "right";
  const dir = side === "right" ? 1 : -1;
  const p0 = { x: side === "right" ? s.x + s.width : s.x, y: sc.y };
  const p1 = { x: side === "right" ? t.x + t.width : t.x, y: tc.y };
  const bulge = Math.min(44, 14 + Math.abs(p1.y - p0.y) * 0.08) * dir;
  const reach = Math.max(p0.x * dir, p1.x * dir) * dir + bulge;
  return cubic(p0, { x: reach, y: p0.y }, { x: reach, y: p1.y }, p1);
}

/** Where the segment from the centre of `r` towards `toward` leaves the box `r`. */
export function exitPoint(r: Rect, toward: Point, radius = 0): Point {
  const c = centerOf(r);
  const dx = toward.x - c.x;
  const dy = toward.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const hw = r.width / 2;
  const hh = r.height / 2;
  const scale = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh);
  // Pull the end in a little at rounded corners, so lines meet the visible outline.
  const inset = radius > 0 ? Math.min(radius * 0.3, 6) / Math.hypot(dx, dy) : 0;
  const k = Math.max(0, scale - inset);
  return { x: c.x + dx * k, y: c.y + dy * k };
}

/** A straight edge between two boxes, from outline to outline. */
export function straightBetween(s: Rect, t: Rect, radius = 0): EdgeRoute {
  const p0 = exitPoint(s, centerOf(t), radius);
  const p1 = exitPoint(t, centerOf(s), radius);
  return {
    path: `M${round(p0.x)},${round(p0.y)} L${round(p1.x)},${round(p1.y)}`,
    label: { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 },
  };
}
