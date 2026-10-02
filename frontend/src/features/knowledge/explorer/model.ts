/**
 * View model shared by both graph explorers (public governance graph and private twin):
 * what a node and an edge look like to the explorer, search, neighbourhoods and the CSS that
 * highlights a neighbourhood. Pure, so it is unit-tested without a browser.
 */
import type { Point, Rect } from "../layout/geometry";

export interface ExplorerItem {
  id: string;
  /** Stable key used in URLs (`?node=<key>`). */
  key: string;
  label: string;
  /** Entity type, e.g. `service`. */
  type: string;
  /** Human name of the type ("Service", "Public rule"). */
  typeLabel: string;
  /** List-view group and filter bucket. */
  group: string;
  summary: string | null;
  /** Other names people search for. */
  aliases: string[];
  rect: Rect;
  /** React Flow node type used to draw it. */
  nodeType: string;
  /** Renderer-specific extras (acronym, review state...). */
  extra: Record<string, unknown>;
}

export interface ExplorerEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  /** Sentence shown when the edge is hovered, e.g. "requires". */
  text: string;
  path: string;
  labelPoint: Point;
  /** Style class suffix (`kg-e-<variant>`). */
  variant: string;
  marker: "ink" | "danger" | null;
  /** A label that is always shown (e.g. "either"), not only on hover. */
  pinnedLabel: string | null;
}

export interface ExplorerHeader {
  id: string;
  title: string;
  count: number;
  rect: Rect;
}

export interface ExplorerGroup {
  id: string;
  title: string;
}

function normalise(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Type-ahead search over labels, aliases, type names and summaries. Earlier, tighter matches
 * rank first: label prefix, then a word in the label, then an alias, then anywhere.
 */
export function searchItems(items: ExplorerItem[], query: string, limit = 8): ExplorerItem[] {
  const q = normalise(query);
  if (!q) return [];
  const terms = q.split(" ");
  const scored: { item: ExplorerItem; score: number }[] = [];
  for (const item of items) {
    const label = normalise(item.label);
    const aliases = item.aliases.map(normalise);
    const type = normalise(item.typeLabel);
    const summary = normalise(item.summary ?? "");
    const hay = `${label} ${aliases.join(" ")} ${type} ${summary}`;
    if (!terms.every((t) => hay.includes(t))) continue;
    let score = 0;
    if (label.startsWith(q)) score += 100;
    else if (` ${label}`.includes(` ${q}`)) score += 70;
    else if (label.includes(q)) score += 50;
    if (aliases.some((a) => a.startsWith(q) || ` ${a}`.includes(` ${q}`))) score += 40;
    if (terms.every((t) => label.includes(t))) score += 20;
    if (type.startsWith(q)) score += 10;
    scored.push({ item, score });
  }
  return scored
    .sort((a, b) => b.score - a.score || a.item.label.length - b.item.label.length || a.item.label.localeCompare(b.item.label))
    .slice(0, limit)
    .map((s) => s.item);
}

/** Items that match a list-view filter query (every word somewhere in the item). */
export function matchesQuery(item: ExplorerItem, query: string): boolean {
  const q = normalise(query);
  if (!q) return true;
  const hay = normalise(`${item.label} ${item.aliases.join(" ")} ${item.typeLabel} ${item.summary ?? ""}`);
  return q.split(" ").every((t) => hay.includes(t));
}

export interface Neighbourhood {
  nodes: Set<string>;
  edges: Set<string>;
}

export function adjacency(edges: Pick<ExplorerEdge, "id" | "source" | "target">[]): Map<string, { node: string; edge: string }[]> {
  const out = new Map<string, { node: string; edge: string }[]>();
  for (const e of edges) {
    out.set(e.source, [...(out.get(e.source) ?? []), { node: e.target, edge: e.id }]);
    out.set(e.target, [...(out.get(e.target) ?? []), { node: e.source, edge: e.id }]);
  }
  return out;
}

/** A node, its direct neighbours and the edges between them. */
export function neighbourhood(id: string, adj: Map<string, { node: string; edge: string }[]>): Neighbourhood {
  const nodes = new Set([id]);
  const edges = new Set<string>();
  for (const link of adj.get(id) ?? []) {
    nodes.add(link.node);
    edges.add(link.edge);
  }
  return { nodes, edges };
}

const attr = (value: string) => value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');

/**
 * CSS that lifts one neighbourhood out of the dimmed graph. Generated instead of re-rendering
 * every node on hover: the canvas gets `data-focus`, and these rules undo the dimming for the
 * focused node, its neighbours and the edges between them.
 */
export function emphasisCss(scope: string, focus: string | null, hood: Neighbourhood | null): string {
  if (!focus || !hood) return "";
  const root = `.kg-canvas[data-kg="${attr(scope)}"][data-focus]`;
  const nodes = [...hood.nodes].map((id) => `[data-id="${attr(id)}"]`).join(",");
  const rules = [`${root} .react-flow__node:is(${nodes}){opacity:1}`, `${root} .react-flow__node[data-id="${attr(focus)}"]{z-index:5 !important}`];
  if (hood.edges.size) {
    const edges = [...hood.edges].map((id) => `[data-id="${attr(id)}"]`).join(",");
    rules.push(`${root} .react-flow__edge:is(${edges}){opacity:1}`, `${root} .react-flow__edge:is(${edges}) .kg-edge{--kg-boost:1.7}`);
  }
  return rules.join("\n");
}

/** Group items for the list view, keeping the group order given and sorting by label. */
export function groupItems(items: ExplorerItem[], groups: ExplorerGroup[]): { group: ExplorerGroup; items: ExplorerItem[] }[] {
  return groups
    .map((group) => ({
      group,
      items: items.filter((i) => i.group === group.id).sort((a, b) => a.label.localeCompare(b.label)),
    }))
    .filter((g) => g.items.length > 0);
}
