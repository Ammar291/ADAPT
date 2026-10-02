/**
 * The public governance graph for mock mode: a snapshot of the backend's cited knowledge
 * graph (`GET /api/graph/governance`: 169 nodes, 353 edges, passage-level evidence from
 * official pages), so mock mode shows exactly the rules and sources the real API does.
 * Parsing is shared with the live adapter (`toGovernanceGraph`).
 */
import type { Citation, Evidence } from "@/domain/common";
import type { KnowledgeGraph, KnowledgeNode, KnowledgeNodeDetail } from "@/domain/graph";
import { toGovernanceGraph } from "../live/governanceFormat";
import snapshot from "./fixtures/governance.json";

const graph: KnowledgeGraph = toGovernanceGraph(snapshot as unknown as Record<string, unknown>);

export const governanceNodes: KnowledgeNode[] = graph.nodes;
export const governanceEdges = graph.edges;

const byKey = new Map(governanceNodes.map((n) => [n.key, n]));
const byId = new Map(governanceNodes.map((n) => [n.id, n]));

export function governanceNode(key: string): KnowledgeNode | undefined {
  return byKey.get(key);
}

/** The authority that provides a service, for "who does this" labels. */
export function authorityOf(key: string): KnowledgeNode | undefined {
  const node = byKey.get(key);
  if (!node) return undefined;
  if (node.type === "authority") return node;
  const edge = governanceEdges.find(
    (e) => (e.relation === "provides" && e.target === node.id) || (e.relation === "provided_by" && e.source === node.id),
  );
  if (!edge) return undefined;
  return byId.get(edge.relation === "provides" ? edge.source : edge.target);
}

/** Evidence for a claim backed by a governance node: its tier and cited passages. */
export function evidenceFor(key: string, note?: string): Evidence {
  const node = byKey.get(key);
  if (!node?.evidence) {
    return { kind: "ai_recommendation", citations: [], confidence: null, note: note ?? null };
  }
  const authority = authorityOf(key);
  const citations: Citation[] = node.evidence.citations.map((c) => ({ ...c, authority: c.authority ?? authority?.label ?? null }));
  return { ...node.evidence, citations, note: note ?? node.evidence.note };
}

export function citationFor(key: string): Citation | null {
  return evidenceFor(key).citations[0] ?? null;
}

export function governanceGraph(filter: { types?: string[]; q?: string } = {}): KnowledgeGraph {
  const q = filter.q?.trim().toLowerCase();
  const nodes = governanceNodes.filter(
    (n) =>
      (!filter.types?.length || filter.types.includes(n.type)) &&
      (!q || n.label.toLowerCase().includes(q) || (n.summary ?? "").toLowerCase().includes(q) || n.key.includes(q)),
  );
  const ids = new Set(nodes.map((n) => n.id));
  return { ...graph, nodes, edges: governanceEdges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
}

export function governanceDetail(ref: string): KnowledgeNodeDetail | null {
  const node = byKey.get(ref) ?? byId.get(ref);
  if (!node) return null;
  const edges = governanceEdges.filter((e) => e.source === node.id || e.target === node.id);
  const neighbourIds = new Set(edges.flatMap((e) => [e.source, e.target]).filter((id) => id !== node.id));
  return { node, edges, neighbours: governanceNodes.filter((n) => neighbourIds.has(n.id)) };
}

/** Keyword search used by the mock assistant: best matches by overlap with label, summary and aliases. */
export function searchGovernance(query: string, limit = 3): KnowledgeNode[] {
  const terms = query
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length > 2);
  if (!terms.length) return [];
  return governanceNodes
    .filter((node) => node.type !== "source")
    .map((node) => {
      const aliases = Array.isArray(node.properties.aliases) ? (node.properties.aliases as string[]).join(" ") : "";
      const hay = `${node.label} ${node.summary ?? ""} ${aliases}`.toLowerCase();
      const score = terms.reduce((sum, t) => sum + (hay.includes(t) ? (node.type === "service" ? 2 : 1) : 0), 0);
      return { node, score };
    })
    .filter((m) => m.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((m) => m.node);
}
