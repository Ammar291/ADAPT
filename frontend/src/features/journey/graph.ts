import { tr } from "@/i18n";
/**
 * Pure view logic for the journey map and list: filters, focus highlighting, edge styling,
 * keyboard neighbours, list grouping and the initial viewport. No React, no I/O.
 */
import { LIFE_AREAS, LIFE_AREA_LABEL, type LifeArea } from "@/domain/common";
import type { Journey, JourneyEdge, JourneyNode } from "@/domain/journey";
import { JOURNEY_FILTERS, matchesFilter, type JourneyFilter } from "@/lib/journey/analysis";
import { BLOCKING_RELATIONS, type TransitLayout } from "./layout";

// --- filters ------------------------------------------------------------------------------------

export function parseFilter(value: string | null | undefined): JourneyFilter {
  return JOURNEY_FILTERS.some((f) => f.id === value) ? (value as JourneyFilter) : "all";
}

/** Keys of nodes that match a filter, or null when nothing is filtered. */
export function filterMatches(journey: Journey, filter: JourneyFilter): Set<string> | null {
  if (filter === "all") return null;
  return new Set(journey.nodes.filter((n) => matchesFilter(n, filter)).map((n) => n.key));
}

// --- focus (selection / hover) -------------------------------------------------------------------

export interface FocusSet {
  key: string;
  /** The focused node, everything it needs (transitively) and what it directly unlocks. */
  nodes: Set<string>;
  edges: Set<string>;
  upstream: Set<string>;
  unlocks: Set<string>;
}

/** The prerequisite chain behind a node, what it unlocks, and its own approvals. */
export function focusSet(journey: Journey, key: string): FocusSet {
  const upstream = new Set<string>();
  const unlocks = new Set<string>();
  const edges = new Set<string>();
  const bySource = new Map<string, JourneyEdge[]>();
  for (const edge of journey.edges) bySource.set(edge.source, [...(bySource.get(edge.source) ?? []), edge]);

  const queue = [key];
  const visited = new Set([key]);
  while (queue.length) {
    const current = queue.shift()!;
    for (const edge of bySource.get(current) ?? []) {
      if (!BLOCKING_RELATIONS.has(edge.relation)) continue;
      edges.add(edge.id);
      upstream.add(edge.target);
      if (!visited.has(edge.target)) {
        visited.add(edge.target);
        queue.push(edge.target);
      }
    }
  }
  for (const edge of journey.edges) {
    if (edge.target === key && BLOCKING_RELATIONS.has(edge.relation)) {
      unlocks.add(edge.source);
      edges.add(edge.id);
    } else if (!BLOCKING_RELATIONS.has(edge.relation) && (edge.source === key || edge.target === key)) {
      // Approvals and bookings attached to the node itself.
      edges.add(edge.id);
      upstream.add(edge.source === key ? edge.target : edge.source);
    }
  }
  upstream.delete(key);
  unlocks.delete(key);
  return { key, nodes: new Set([key, ...upstream, ...unlocks]), edges, upstream, unlocks };
}

export type NodeEmphasis = "normal" | "dimmed" | "related" | "focused";

export function nodeEmphasis(key: string, focus: FocusSet | null, matches: Set<string> | null): NodeEmphasis {
  if (focus) {
    if (focus.key === key) return "focused";
    return focus.nodes.has(key) ? "related" : "dimmed";
  }
  if (matches && !matches.has(key)) return "dimmed";
  return "normal";
}

// --- edges -----------------------------------------------------------------------------------------

/** Edges linking consecutive steps of the critical path. */
export function criticalEdges(journey: Journey, path: string[]): Set<string> {
  const pairs = new Set<string>();
  for (let i = 0; i + 1 < path.length; i++) pairs.add(`${path[i + 1]}>${path[i]}`);
  return new Set(journey.edges.filter((e) => BLOCKING_RELATIONS.has(e.relation) && pairs.has(`${e.source}>${e.target}`)).map((e) => e.id));
}

export type EdgeTone = "base" | "settled" | "critical" | "danger" | "danger-soft" | "focus";

export interface EdgeVisual {
  tone: EdgeTone;
  /** SVG dash array; undefined for a solid line. */
  dash: string | undefined;
  width: number;
  dimmed: boolean;
  /** "either" for alternatives (edges sharing an `anyOf` group). */
  label: string | null;
}

export interface EdgeContext {
  nodes: Map<string, JourneyNode>;
  critical: Set<string>;
  focus: FocusSet | null;
  matches: Set<string> | null;
  anyOfSizes: Map<string, number>;
}

/** A step's alternatives: edges from the same step sharing an `anyOf` group. */
export function anyOfKey(edge: JourneyEdge): string | null {
  return edge.anyOf ? `${edge.source}|${edge.anyOf}` : null;
}

export function anyOfSizes(journey: Journey): Map<string, number> {
  const sizes = new Map<string, number>();
  for (const edge of journey.edges) {
    const key = anyOfKey(edge);
    if (key) sizes.set(key, (sizes.get(key) ?? 0) + 1);
  }
  return sizes;
}

const DASH: Record<JourneyEdge["relation"], string | undefined> = {
  depends_on: undefined,
  requires: "6 5",
  blocked_by: "0.5 5",
  approves: "0.5 5",
  books: "6 5",
};

const unfinished = (node: JourneyNode | undefined) => Boolean(node && node.status !== "done" && node.status !== "not_applicable");

/**
 * How an edge looks. `edge.target` is the prerequisite and `edge.source` the dependent step.
 * Precedence: the focused chain (ink), then the cause of a block (danger), then the critical
 * path (teal), then a block passed down from an earlier blocked step (soft danger). Edges from
 * a prerequisite that's already met are "settled": drawn quietly, since they no longer matter.
 */
export function edgeVisual(edge: JourneyEdge, ctx: EdgeContext): EdgeVisual {
  const prerequisite = ctx.nodes.get(edge.target);
  const dependent = ctx.nodes.get(edge.source);
  const critical = ctx.critical.has(edge.id);
  const inFocus = ctx.focus?.edges.has(edge.id) ?? false;
  const blocking = BLOCKING_RELATIONS.has(edge.relation) && dependent?.status === "blocked" && unfinished(prerequisite);

  let tone: EdgeTone = "base";
  if (inFocus) tone = "focus";
  else if (edge.relation === "blocked_by" || (blocking && prerequisite?.status !== "blocked")) tone = "danger";
  else if (critical) tone = "critical";
  else if (blocking) tone = "danger-soft";
  else if (!unfinished(prerequisite)) tone = "settled";

  const dimmed = ctx.focus
    ? !inFocus
    : ctx.matches
      ? !(ctx.matches.has(edge.source) && ctx.matches.has(edge.target))
      : false;

  return {
    tone,
    dash: DASH[edge.relation],
    width: tone === "focus" ? 2 : critical ? 2.25 : tone === "danger" ? 1.75 : tone === "settled" ? 1.25 : 1.5,
    dimmed,
    label: (ctx.anyOfSizes.get(anyOfKey(edge) ?? "") ?? 0) > 1 ? "either" : null,
  };
}

// --- keyboard ---------------------------------------------------------------------------------------

export type Direction = "left" | "right" | "up" | "down";

export const ARROW_DIRECTION: Record<string, Direction> = {
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  ArrowDown: "down",
};

/** The nearest node in a direction, favouring nodes in line with the current one. */
export function neighbour(
  nodes: { key: string; x: number; y: number; width: number; height: number }[],
  from: string,
  direction: Direction,
): string | null {
  const origin = nodes.find((n) => n.key === from);
  if (!origin) return null;
  const cx = origin.x + origin.width / 2;
  const cy = origin.y + origin.height / 2;
  let best: { key: string; score: number } | null = null;
  for (const node of nodes) {
    if (node.key === from) continue;
    const dx = node.x + node.width / 2 - cx;
    const dy = node.y + node.height / 2 - cy;
    const primary = direction === "left" ? -dx : direction === "right" ? dx : direction === "up" ? -dy : dy;
    const secondary = direction === "left" || direction === "right" ? Math.abs(dy) : Math.abs(dx);
    if (primary <= 1) continue;
    const score = primary + secondary * 2.5;
    if (!best || score < best.score) best = { key: node.key, score };
  }
  return best?.key ?? null;
}

// --- list ---------------------------------------------------------------------------------------------

export type ListGrouping = "area" | "stage";

export interface ListGroup {
  id: string;
  title: string;
  description: string | null;
  area: LifeArea | null;
  nodes: JourneyNode[];
}

/** The list alternative to the map: filtered for real, grouped by life area or by stage. */
export function listGroups(journey: Journey, layout: TransitLayout, filter: JourneyFilter, by: ListGrouping): ListGroup[] {
  const order = new Map(journey.nodes.map((n, i) => [n.key, i]));
  const column = (n: JourneyNode) => layout.byKey.get(n.key)?.column ?? 0;
  const areaIndex = (n: JourneyNode) => LIFE_AREAS.indexOf(n.area);
  const nodes = journey.nodes.filter((n) => matchesFilter(n, filter));

  if (by === "area") {
    return LIFE_AREAS.map((area) => ({
      id: area,
      title: LIFE_AREA_LABEL[area],
      description: null,
      area,
      nodes: nodes.filter((n) => n.area === area).sort((a, b) => column(a) - column(b) || order.get(a.key)! - order.get(b.key)!),
    })).filter((g) => g.nodes.length > 0);
  }

  const stages = [...new Set(nodes.map(column))].sort((a, b) => a - b);
  return stages.map((stage) => ({
    id: `stage-${stage}`,
    title: tr("copy.stage_v0_63511ee", { v0: stage + 1 }),
    description: stage === 0 ? tr("copy.nothing_needs_to_happen_first_fc02ca8") : stage === 1 ? tr("copy.after_one_earlier_step_9f044a3") : `After ${stage} earlier steps in a row`,
    area: null,
    nodes: nodes.filter((n) => column(n) === stage).sort((a, b) => areaIndex(a) - areaIndex(b) || order.get(a.key)! - order.get(b.key)!),
  }));
}

// --- viewport --------------------------------------------------------------------------------------------

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

/**
 * Where the map opens: the whole map when it fits at a readable zoom; otherwise as much of
 * its width as stays readable, from the top, so every line starts in view and the rest is
 * a scroll away.
 */
export function initialViewport(
  content: { width: number; height: number },
  canvas: { width: number; height: number },
  { padding = 24, minZoom = 0.6, maxZoom = 1 }: { padding?: number; minZoom?: number; maxZoom?: number } = {},
): Viewport {
  const fitWidth = (canvas.width - padding * 2) / content.width;
  const fitHeight = (canvas.height - padding * 2) / content.height;
  const fitAll = Math.min(fitWidth, fitHeight);
  if (fitAll >= minZoom) {
    const zoom = Math.min(fitAll, maxZoom);
    return { zoom, x: (canvas.width - content.width * zoom) / 2, y: (canvas.height - content.height * zoom) / 2 };
  }
  const zoom = Math.min(Math.max(fitWidth, minZoom), maxZoom);
  const width = content.width * zoom;
  return { zoom, x: width <= canvas.width ? (canvas.width - width) / 2 : 0, y: 0 };
}

/**
 * Keeps the map covering the visible area: never pans past the start of the lines or the
 * top of the map (which would leave empty canvas and float the line labels), nor past its end.
 */
export function clampViewport(
  viewport: Viewport,
  content: { width: number; height: number },
  area: { right: number; bottom: number; top: number },
  padding = 24,
): Viewport {
  const { zoom } = viewport;
  const clampAxis = (value: number, size: number, start: number, end: number) => {
    const min = end - size * zoom - padding;
    const max = start;
    return min > max ? max : Math.min(max, Math.max(min, value));
  };
  return {
    zoom,
    x: clampAxis(viewport.x, content.width, 0, area.right),
    y: clampAxis(viewport.y, content.height, area.top, area.bottom),
  };
}
