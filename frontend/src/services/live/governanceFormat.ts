/**
 * Governance graph wire format → domain. Accepts the cited knowledge-graph format
 * (`entity_type`, `relation`, `evidence_kind`, `evidence_ids` resolved against a top-level
 * `evidence` list of passages) and the earlier seed format (`type`, `provenance`).
 * Used by the live adapter and by the mock fixture, so both read the graph the same way.
 */
import type { Citation, Evidence, EvidenceKind } from "@/domain/common";
import type { KnowledgeEdge, KnowledgeGraph, KnowledgeNode } from "@/domain/graph";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function toCitation(passage: Raw): Citation {
  return {
    title: passage.source_title ?? passage.title ?? "",
    url: passage.source_url ?? passage.url ?? "",
    authority: passage.authority ?? null,
    retrievedAt: passage.retrieved_at ?? null,
    section: passage.section_or_page ?? passage.section ?? null,
    quote: passage.quote ?? passage.claim ?? null,
    excerpt: passage.excerpt,
    effectiveDate: passage.effective_date ?? null,
    freshness: passage.freshness,
    sourceFamily: passage.source_family ?? null,
    chunkId: passage.chunk_id ?? passage.rag_chunk_id ?? null,
  };
}

function evidenceOf(raw: Raw, passages: Map<string, Raw>): Evidence | null {
  if (raw.provenance) {
    const p = raw.provenance as Raw;
    return {
      kind: p.kind as EvidenceKind,
      citations: (p.citations ?? []).map(toCitation),
      confidence: p.confidence ?? null,
      note: p.note ?? null,
    };
  }
  if (!raw.evidence_kind) return null;
  const cited = ((raw.evidence_ids ?? []) as string[]).map((id) => passages.get(id)).filter((p): p is Raw => Boolean(p));
  const confidences = cited.map((p) => p.confidence).filter((c): c is number => typeof c === "number");
  return {
    kind: raw.evidence_kind as EvidenceKind,
    citations: cited.map(toCitation),
    confidence: confidences.length ? Math.max(...confidences) : null,
    note: null,
  };
}

export function toGovernanceNode(raw: Raw, passages: Map<string, Raw> = new Map()): KnowledgeNode {
  return {
    id: raw.id,
    key: raw.key,
    scope: "governance",
    type: raw.entity_type ?? raw.type,
    label: raw.label,
    summary: raw.summary ?? null,
    properties: raw.properties ?? raw.properties_json ?? {},
    evidence: evidenceOf(raw, passages),
    officialUrl: raw.official_url ?? null,
    facts: {},
  };
}

export function toGovernanceEdge(raw: Raw): KnowledgeEdge {
  const properties = (raw.properties ?? {}) as Raw;
  return {
    id: raw.id,
    scope: "governance",
    source: raw.source ?? raw.source_node_id,
    target: raw.target ?? raw.target_node_id,
    relation: raw.relation ?? raw.type,
    label: raw.label ?? null,
    anyOf: typeof properties.any_of === "string" ? properties.any_of : null,
    properties,
  };
}

export function toGovernanceGraph(raw: Raw): KnowledgeGraph {
  const passages = new Map<string, Raw>(((raw.evidence ?? []) as Raw[]).map((p) => [p.id, p]));
  return {
    nodes: ((raw.nodes ?? []) as Raw[]).map((n) => toGovernanceNode(n, passages)),
    edges: ((raw.edges ?? []) as Raw[]).map(toGovernanceEdge),
    linkedNodes: [],
    generatedAt: raw.generated_at ?? new Date().toISOString(),
  };
}
