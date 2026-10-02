/**
 * Transit-map layout for the journey graph. Pure and deterministic: the same journey always
 * produces the same map.
 *
 *   rows ("lines")  — one band per life area present, in LIFE_AREAS order
 *   columns         — dependency depth (`depthOf`), so order flows left to right
 *   cells           — (column, area); stations (task / appointment / completed action) stack
 *                     first, satellites (document / requirement / dependency / approval) hang
 *                     below them as smaller pills
 *
 * Two refinements keep the map readable without breaking left-to-right order:
 *   - Satellites with no prerequisites of their own are pulled right, to sit one column
 *     before the first step that needs them (never left of their own depth). A document
 *     needed only for the spouse visa sits next to it instead of at the far start.
 *   - An approval sits directly under the step it gates, in the same cell.
 */
import { LIFE_AREAS, type LifeArea } from "@/domain/common";
import type { Journey, JourneyEdge, JourneyNode, JourneyNodeKind } from "@/domain/journey";
import { depthOf } from "@/lib/journey/analysis";

export type NodeRole = "station" | "satellite";

const STATION_KINDS: ReadonlySet<JourneyNodeKind> = new Set(["task", "appointment", "action"]);

export function roleOf(kind: JourneyNodeKind): NodeRole {
  return STATION_KINDS.has(kind) ? "station" : "satellite";
}

/** Relations that order the plan (the same set `prerequisites` uses). */
export const BLOCKING_RELATIONS: ReadonlySet<JourneyEdge["relation"]> = new Set(["depends_on", "requires", "blocked_by"]);

export const LAYOUT = {
  /** Room at the start of every line for its sticky label. */
  gutter: 196,
  stationWidth: 232,
  stationHeight: 104,
  /** Completed stations are quieter and shorter: the past takes less room than the future. */
  doneStationHeight: 52,
  pillWidth: 200,
  pillHeight: 40,
  columnGap: 88,
  bandPadTop: 24,
  bandPadBottom: 24,
  stationGap: 12,
  /** Between a station and the first pill hanging below it. */
  satelliteGap: 14,
  pillGap: 10,
  endPad: 72,
} as const;

export interface PlacedNode {
  key: string;
  role: NodeRole;
  area: LifeArea;
  column: number;
  x: number;
  y: number;
  width: number;
  height: number;
  /** For approvals: the step they gate. */
  parentKey: string | null;
}

export interface Band {
  area: LifeArea;
  index: number;
  y: number;
  height: number;
  /** The line runs through the centre of the first station row... */
  lineY: number;
  /** ...and ends at the band's last node. */
  lineEnd: number;
  done: number;
  total: number;
}

export interface TransitLayout {
  nodes: PlacedNode[];
  byKey: Map<string, PlacedNode>;
  bands: Band[];
  columns: number;
  width: number;
  height: number;
}

export function columnX(column: number): number {
  return LAYOUT.gutter + column * (LAYOUT.stationWidth + LAYOUT.columnGap);
}

function heightOf(node: JourneyNode): number {
  if (roleOf(node.kind) === "satellite") return LAYOUT.pillHeight;
  return node.status === "done" ? LAYOUT.doneStationHeight : LAYOUT.stationHeight;
}

/** The step each approval gates (source of its `approves` edge). */
export function approvalParents(journey: Journey): Map<string, string> {
  const kinds = new Map(journey.nodes.map((n) => [n.key, n.kind]));
  const parents = new Map<string, string>();
  for (const edge of journey.edges) {
    if (edge.relation !== "approves" || kinds.get(edge.target) !== "approval" || !kinds.has(edge.source)) continue;
    if (!parents.has(edge.target)) parents.set(edge.target, edge.source);
  }
  return parents;
}

/** Column of every node: its depth, with satellites pulled right and approvals under their step. */
export function assignColumns(journey: Journey): Map<string, number> {
  const depth = depthOf(journey);
  const keys = new Set(journey.nodes.map((n) => n.key));
  const consumers = new Map<string, string[]>();
  const hasPrerequisite = new Set<string>();
  for (const edge of journey.edges) {
    if (!BLOCKING_RELATIONS.has(edge.relation) || !keys.has(edge.source) || !keys.has(edge.target)) continue;
    consumers.set(edge.target, [...(consumers.get(edge.target) ?? []), edge.source]);
    hasPrerequisite.add(edge.source);
  }
  const parents = approvalParents(journey);
  const column = new Map<string, number>();
  const d = (key: string) => depth.get(key) ?? 0;

  // Deepest first, so a satellite's consumers are placed before it is.
  const ordered = journey.nodes
    .map((node, index) => ({ node, index }))
    .filter(({ node }) => !parents.has(node.key))
    .sort((a, b) => d(b.node.key) - d(a.node.key) || a.index - b.index);
  for (const { node } of ordered) {
    const own = d(node.key);
    const users = consumers.get(node.key) ?? [];
    if (roleOf(node.kind) === "satellite" && !hasPrerequisite.has(node.key) && users.length) {
      const earliest = Math.min(...users.map((u) => column.get(u) ?? d(u)));
      column.set(node.key, Math.max(own, earliest - 1));
    } else {
      column.set(node.key, own);
    }
  }
  // Approvals follow their step (resolving chains of approvals defensively).
  for (const [approval, parent] of parents) {
    let target = parent;
    const seen = new Set<string>([approval]);
    while (parents.has(target) && !seen.has(target)) {
      seen.add(target);
      target = parents.get(target)!;
    }
    column.set(approval, column.get(target) ?? d(target));
  }
  return column;
}

/** Nodes of one cell in stacking order: stations, then satellites, each followed by its approvals. */
function stackCell(cell: JourneyNode[], parents: Map<string, string>): JourneyNode[] {
  const inCell = new Set(cell.map((n) => n.key));
  const approvalsOf = new Map<string, JourneyNode[]>();
  const loose: JourneyNode[] = [];
  for (const node of cell) {
    const parent = parents.get(node.key);
    if (parent === undefined) continue;
    if (inCell.has(parent)) approvalsOf.set(parent, [...(approvalsOf.get(parent) ?? []), node]);
    else loose.push(node);
  }
  const stacked: JourneyNode[] = [];
  const push = (node: JourneyNode) => {
    stacked.push(node);
    for (const approval of approvalsOf.get(node.key) ?? []) push(approval);
  };
  const primary = cell.filter((n) => !parents.has(n.key));
  primary.filter((n) => roleOf(n.kind) === "station").forEach(push);
  primary.filter((n) => roleOf(n.kind) === "satellite").forEach(push);
  loose.forEach(push);
  return stacked;
}

export function buildTransitLayout(journey: Journey): TransitLayout {
  const columns = assignColumns(journey);
  const parents = approvalParents(journey);
  const areas = LIFE_AREAS.filter((area) => journey.nodes.some((n) => n.area === area));
  const stationCenter = LAYOUT.bandPadTop + LAYOUT.stationHeight / 2;

  // Pass 1: offsets inside each band.
  const offsets = new Map<string, number>();
  const bandContent = new Map<LifeArea, number>();
  for (const area of areas) {
    const inArea = journey.nodes.filter((n) => n.area === area);
    const cols = [...new Set(inArea.map((n) => columns.get(n.key) ?? 0))].sort((a, b) => a - b);
    let content: number = LAYOUT.stationHeight;
    for (const col of cols) {
      const stacked = stackCell(
        inArea.filter((n) => (columns.get(n.key) ?? 0) === col),
        parents,
      );
      const first = stacked[0];
      if (!first) continue;
      // The first node of every cell is centred on the line, so the line runs through it
      // (a cell with no station puts its first pill on the line itself).
      let y = stationCenter - heightOf(first) / 2;
      let previous: JourneyNode | null = null;
      for (const node of stacked) {
        if (previous) {
          const prevRole = roleOf(previous.kind);
          const role = roleOf(node.kind);
          y +=
            heightOf(previous) +
            (role === "station" ? LAYOUT.stationGap : prevRole === "station" ? LAYOUT.satelliteGap : LAYOUT.pillGap);
        }
        offsets.set(node.key, y);
        previous = node;
      }
      if (previous) content = Math.max(content, y + heightOf(previous) - LAYOUT.bandPadTop);
    }
    bandContent.set(area, content);
  }

  // Pass 2: absolute positions.
  const bands: Band[] = [];
  let top = 0;
  areas.forEach((area, index) => {
    const height = LAYOUT.bandPadTop + (bandContent.get(area) ?? LAYOUT.stationHeight) + LAYOUT.bandPadBottom;
    const counted = journey.nodes.filter((n) => n.area === area && n.status !== "not_applicable" && n.kind !== "approval" && n.kind !== "dependency");
    const ends = journey.nodes
      .filter((n) => n.area === area)
      .map((n) => columnX(columns.get(n.key) ?? 0) + LAYOUT.stationWidth);
    bands.push({
      area,
      index,
      y: top,
      height,
      lineY: top + stationCenter,
      lineEnd: Math.max(LAYOUT.gutter, ...ends),
      done: counted.filter((n) => n.status === "done").length,
      total: counted.length,
    });
    top += height;
  });
  const bandByArea = new Map(bands.map((b) => [b.area, b]));

  const nodes: PlacedNode[] = journey.nodes.map((node) => {
    const role = roleOf(node.kind);
    const column = columns.get(node.key) ?? 0;
    const band = bandByArea.get(node.area)!;
    const width = role === "station" ? LAYOUT.stationWidth : LAYOUT.pillWidth;
    return {
      key: node.key,
      role,
      area: node.area,
      column,
      x: columnX(column) + (LAYOUT.stationWidth - width) / 2,
      y: band.y + (offsets.get(node.key) ?? LAYOUT.bandPadTop),
      width,
      height: heightOf(node),
      parentKey: parents.get(node.key) ?? null,
    };
  });

  const columnCount = nodes.length ? Math.max(...nodes.map((n) => n.column)) + 1 : 0;
  return {
    nodes,
    byKey: new Map(nodes.map((n) => [n.key, n])),
    bands,
    columns: columnCount,
    width: columnX(Math.max(columnCount, 1)) - LAYOUT.columnGap + LAYOUT.endPad,
    height: top,
  };
}
