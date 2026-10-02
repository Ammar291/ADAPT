/**
 * Live private user graph (`/api/graph/user`): the person's digital twin.
 * The only code that knows its wire format. Governance nodes the twin links to arrive
 * separately (`linkedNodes`) and are public reference knowledge, never personal facts.
 */
import type { FactSource, KnowledgeEdge, KnowledgeGraph, KnowledgeNode, TwinFact } from "@/domain/graph";
import { api } from "@/lib/api/client";
import type { GraphService } from "../types";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const userGraphPaths = {
  graph: "/graph/user",
  schema: "/graph/user/schema",
  facts: "/graph/user/facts",
  fact: (id: string) => `/graph/user/facts/${encodeURIComponent(id)}`,
  personalisation: "/graph/user/personalisation",
  explain: "/graph/user/explain",
} as const;

function toFact(raw: Raw): TwinFact {
  return {
    value: raw.value,
    source: raw.source as FactSource,
    // Where the fact came from, as a pointer the UI can show or link: the source document,
    // else another origin such as the onboarding profile.
    sourceRef: raw.source_document_id ? `document:${raw.source_document_id}` : (raw.source_ref ?? null),
    confidence: typeof raw.confidence === "number" ? raw.confidence : 1,
    confirmedByUser: raw.confirmed_by_user === true,
    observedAt: raw.observed_at ?? null,
  };
}

/**
 * Facts keyed by attribute. An accepted value wins over a proposal awaiting review for
 * the same attribute; a lone proposal is shown (with its lower confidence, unconfirmed).
 */
export function factsByAttribute(facts: Raw[]): Record<string, TwinFact> {
  const out: Record<string, TwinFact> = {};
  const accepted = new Set<string>();
  for (const fact of facts) {
    if (fact.status === "accepted") {
      out[fact.attribute] = toFact(fact);
      accepted.add(fact.attribute);
    } else if (!accepted.has(fact.attribute) && fact.value !== null && fact.value !== undefined) {
      out[fact.attribute] = toFact(fact);
    }
  }
  return out;
}

function toUserNode(raw: Raw): KnowledgeNode {
  return {
    id: raw.id,
    key: raw.key,
    scope: "user",
    type: raw.type,
    label: raw.label,
    summary: null,
    properties: {},
    evidence: null,
    officialUrl: null,
    facts: factsByAttribute(raw.facts ?? []),
  };
}

function toGovernanceNode(raw: Raw): KnowledgeNode {
  return {
    id: raw.id,
    key: raw.key,
    scope: "governance",
    type: raw.entity_type ?? raw.type,
    label: raw.label,
    summary: raw.summary ?? null,
    properties: raw.properties ?? {},
    evidence: null,
    officialUrl: raw.official_url ?? null,
    facts: {},
  };
}

function toUserEdge(raw: Raw): KnowledgeEdge {
  return {
    id: raw.id,
    // Every edge here is private, including links from the twin to public knowledge.
    scope: "user",
    source: raw.source,
    target: raw.target,
    relation: raw.relation,
    label: null,
    anyOf: null,
  };
}

export function toUserGraph(raw: Raw): KnowledgeGraph {
  return {
    nodes: (raw.nodes ?? []).map(toUserNode),
    edges: (raw.edges ?? []).map(toUserEdge),
    linkedNodes: (raw.linked_governance_nodes ?? []).map(toGovernanceNode),
    generatedAt: raw.generated_at ?? new Date().toISOString(),
  };
}

export const liveUserGraph: Pick<GraphService, "user"> = {
  async user(signal) {
    return toUserGraph(await api.get<Raw>(userGraphPaths.graph, { signal }));
  },
};
