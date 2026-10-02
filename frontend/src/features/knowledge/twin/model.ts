import { tr } from "@/i18n";
/**
 * The private digital twin as the explorer shows it: a radial map centred on the person, with
 * the public rules it links to on an outer ring. Pure (unit-tested).
 */
import { RELATION_LABEL, USER_TYPE_LABEL, type KnowledgeEdge, type KnowledgeGraph, type KnowledgeNode } from "@/domain/graph";
import type { ExplorerEdge, ExplorerGroup, ExplorerItem } from "../explorer/model";
import { formatDate } from "@/lib/format";
import type { Rect } from "../layout/geometry";
import { radialLayout } from "../layout/radial";

export const TWIN_GROUPS: ExplorerGroup[] = [
  { id: "people", title: tr("copy.people_b37554f", { lng: "en" }) },
  { id: "goals", title: tr("copy.goals_48d8c62", { lng: "en" }) },
  { id: "organisation", title: tr("copy.organisation_6e99c1d", { lng: "en" }) },
  { id: "documents", title: tr("copy.documents_687c828", { lng: "en" }) },
  { id: "preferences", title: tr("copy.preferences_and_constraints_94880de", { lng: "en" }) },
  { id: "milestones", title: tr("copy.milestones_e7bdefe", { lng: "en" }) },
  { id: "other", title: tr("copy.other_6e6a6f2", { lng: "en" }) },
  { id: "public", title: tr("copy.public_rules_your_twin_links_to_e3eacc8", { lng: "en" }) },
];

const GROUP_OF_TYPE: Record<string, string> = {
  person: "people",
  goal: "goals",
  organization: "organisation",
  document: "documents",
  preference: "preferences",
  constraint: "preferences",
  milestone: "milestones",
};

/** Second-ring order: goals first (top right), then what supports them. */
const RING_ORDER = ["goal", "organization", "document", "milestone", "preference", "constraint"];

/** Relations that cross from the private twin to public rules. */
export const CROSS_RELATIONS = new Set(["pursues", "satisfies", "instance_of", "eligible_for", "blocked_by"]);

export function twinTypeLabel(node: KnowledgeNode): string {
  if (node.scope === "governance") return tr("copy.public_rule_2878b51");
  return USER_TYPE_LABEL[node.type] ?? node.type.charAt(0).toUpperCase() + node.type.slice(1).replace(/_/g, " ");
}

/** The person the twin is about: `person.you`, else the first person. */
export function centreOf(graph: KnowledgeGraph): KnowledgeNode | null {
  return graph.nodes.find((n) => n.key === "person.you") ?? graph.nodes.find((n) => n.type === "person") ?? graph.nodes[0] ?? null;
}

/** Public rules the twin links to, without duplicates of its own nodes. */
export function linkedPublicNodes(graph: KnowledgeGraph): KnowledgeNode[] {
  const own = new Set(graph.nodes.map((n) => n.id));
  const seen = new Set<string>();
  return graph.linkedNodes.filter((n) => !own.has(n.id) && !seen.has(n.id) && seen.add(n.id));
}

const SIZE = {
  centre: { width: 208, height: 56 },
  person: { width: 184, height: 46 },
  own: { width: 212, height: 46 },
  public: { width: 190, height: 52 },
};

/** Labels can carry ISO dates ("Arrive by 2026-11-12"); show them the way people write dates. */
export function readableLabel(label: string): string {
  return label.replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (iso) => formatDate(iso) || iso);
}

export interface TwinMap {
  items: ExplorerItem[];
  edges: ExplorerEdge[];
  bounds: Rect;
  centreId: string | null;
}

export function edgeVariant(edge: KnowledgeEdge, publicIds: Set<string>): "private" | "cross" | "blocked" {
  if (edge.relation === "blocked_by") return "blocked";
  return publicIds.has(edge.source) || publicIds.has(edge.target) || CROSS_RELATIONS.has(edge.relation) ? "cross" : "private";
}

export function buildTwinMap(graph: KnowledgeGraph, aspect: number): TwinMap {
  const centre = centreOf(graph);
  const publicNodes = linkedPublicNodes(graph);
  const publicIds = new Set(publicNodes.map((n) => n.id));
  const all = [...graph.nodes, ...publicNodes];
  const byId = new Map(all.map((n) => [n.id, n]));
  const edges = graph.edges.filter((e) => byId.has(e.source) && byId.has(e.target) && e.source !== e.target);

  const layout = radialLayout(
    all.map((n) => ({ id: n.id, type: n.type, label: n.label })),
    edges.map((e) => ({ id: e.id, source: e.source, target: e.target, relation: e.relation })),
    {
      centerId: centre?.id ?? "",
      aspect,
      ring: (n) => (publicIds.has(n.id) ? 3 : n.type === "person" ? 1 : 2),
      size: (n) => (n.id === centre?.id ? SIZE.centre : publicIds.has(n.id) ? SIZE.public : n.type === "person" ? SIZE.person : SIZE.own),
      compare: (a, b) => {
        const rank = (t: string) => (RING_ORDER.indexOf(t) < 0 ? RING_ORDER.length : RING_ORDER.indexOf(t));
        return rank(a.type) - rank(b.type) || a.label.localeCompare(b.label);
      },
      radius: (n) => (publicIds.has(n.id) ? 6 : 22),
    },
  );

  const items: ExplorerItem[] = all.map((n) => {
    const isPublic = publicIds.has(n.id);
    return {
      id: n.id,
      key: n.key,
      label: readableLabel(n.label),
      type: n.type,
      typeLabel: twinTypeLabel(n),
      group: isPublic ? "public" : (GROUP_OF_TYPE[n.type] ?? "other"),
      summary: n.summary,
      aliases: [],
      rect: layout.nodes.get(n.id)!,
      nodeType: isPublic ? "public" : "twin",
      extra: {
        centre: n.id === centre?.id,
        needsReview: Object.values(n.facts).some((f) => !f.confirmedByUser),
        factCount: Object.keys(n.facts).length,
      },
    };
  });

  const explorerEdges: ExplorerEdge[] = edges.map((e) => {
    const route = layout.edges.get(e.id)!;
    const variant = edgeVariant(e, publicIds);
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      relation: e.relation,
      text: RELATION_LABEL[e.relation] ?? e.relation.replace(/_/g, " "),
      path: route.path,
      labelPoint: route.label,
      variant,
      marker: variant === "blocked" ? "danger" : null,
      pinnedLabel: variant === "blocked" ? tr("copy.blocked_by_95bfd07") : null,
    };
  });

  return { items, edges: explorerEdges, bounds: layout.bounds, centreId: centre?.id ?? null };
}

// --- details --------------------------------------------------------------------------------------

const OUTGOING: Record<string, string> = {
  has_goal: tr("copy.wants_to_0679a84", { lng: "en" }),
  holds_document: tr("copy.holds_b1c8168", { lng: "en" }),
  spouse_of: tr("copy.spouse_04aee08", { lng: "en" }),
  founder_of: tr("copy.founder_of_2cad699", { lng: "en" }),
  prefers: tr("copy.prefers_d2c5cc3", { lng: "en" }),
  constrained_by: tr("copy.constrained_by_5c66348", { lng: "en" }),
  dependent_of: tr("copy.dependant_of_1e50b15", { lng: "en" }),
  pursues: tr("copy.pursues_001ee71", { lng: "en" }),
  satisfies: tr("copy.counts_as_6bba9b8", { lng: "en" }),
  instance_of: tr("copy.is_a_b0e9b5d", { lng: "en" }),
  eligible_for: tr("copy.may_be_eligible_for_92cddd4", { lng: "en" }),
  blocked_by: tr("copy.blocked_by_ea05d77", { lng: "en" }),
  located_in: tr("copy.located_in_179a181", { lng: "en" }),
};

const INCOMING: Record<string, string> = {
  has_goal: tr("copy.goal_of_b292d97", { lng: "en" }),
  holds_document: tr("copy.held_by_0d4a738", { lng: "en" }),
  spouse_of: tr("copy.spouse_04aee08", { lng: "en" }),
  founder_of: tr("copy.founded_by_013c7d3", { lng: "en" }),
  prefers: tr("copy.preference_of_11acfb9", { lng: "en" }),
  constrained_by: tr("copy.applies_to_0c9d314", { lng: "en" }),
  dependent_of: tr("copy.dependants_69d8000", { lng: "en" }),
  pursues: tr("copy.your_goals_that_pursue_it_784b761", { lng: "en" }),
  satisfies: tr("copy.your_documents_that_count_f1bdd6a", { lng: "en" }),
  instance_of: tr("copy.your_copy_f851b8f", { lng: "en" }),
  eligible_for: tr("copy.linked_from_your_twin_eac2b3b", { lng: "en" }),
  blocked_by: tr("copy.what_it_blocks_for_you_37862fe", { lng: "en" }),
  located_in: tr("copy.linked_from_your_twin_eac2b3b", { lng: "en" }),
};

export interface TwinConnection {
  title: string;
  items: { node: KnowledgeNode; relation: string; isPublic: boolean }[];
}

/** A twin node's links grouped by what they mean from its point of view. */
export function twinConnections(nodeId: string, graph: KnowledgeGraph): TwinConnection[] {
  const publicNodes = linkedPublicNodes(graph);
  const publicIds = new Set(publicNodes.map((n) => n.id));
  const byId = new Map([...graph.nodes, ...publicNodes].map((n) => [n.id, n]));
  const groups = new Map<string, TwinConnection>();
  for (const e of graph.edges) {
    const outgoing = e.source === nodeId;
    if (!outgoing && e.target !== nodeId) continue;
    const other = byId.get(outgoing ? e.target : e.source);
    if (!other || other.id === nodeId) continue;
    const title = (outgoing ? OUTGOING : INCOMING)[e.relation] ?? (RELATION_LABEL[e.relation] ?? e.relation).replace(/^./, (c) => c.toUpperCase());
    const group = groups.get(title) ?? { title, items: [] };
    if (!group.items.some((i) => i.node.id === other.id)) group.items.push({ node: other, relation: e.relation, isPublic: publicIds.has(other.id) });
    groups.set(title, group);
  }
  return [...groups.values()];
}
