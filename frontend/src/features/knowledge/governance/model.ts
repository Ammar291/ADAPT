import { formatNumber, formatCurrency } from "@/lib/format";
import { tr } from "@/i18n";
/**
 * The public governance graph as the explorer shows it: which columns, how edges look, how a
 * node's neighbours read in the details panel, and plain-language eligibility conditions.
 * Pure functions (unit-tested).
 */
import { GOVERNANCE_SOURCE_TYPES, GOVERNANCE_TYPE_LABEL, RELATION_LABEL, type KnowledgeEdge, type KnowledgeGraph, type KnowledgeNode } from "@/domain/graph";
import type { ExplorerEdge, ExplorerGroup, ExplorerHeader, ExplorerItem } from "../explorer/model";
import { columnLayout, type ColumnSpec } from "../layout/columns";
import type { Rect } from "../layout/geometry";

const NODE = { width: 196, height: 50 };

/** Left to right: what you must meet, what you bring, what you do, where, and who runs it. */
export const GOVERNANCE_COLUMNS: ColumnSpec[] = [
  { id: "requirements", title: tr("copy.requirements_09a428f", { lng: "en" }), types: ["requirement", "eligibility_rule", "fee"], ...NODE },
  { id: "documents", title: tr("copy.documents_687c828", { lng: "en" }), types: ["document", "document_type"], ...NODE },
  { id: "services", title: tr("copy.services_5cbd584", { lng: "en" }), types: ["service", "appointment", "dependency", "process_step"], width: 228, height: 56, hub: true, fallback: true },
  { id: "channels", title: tr("copy.where_to_apply_b48c089", { lng: "en" }), types: ["portal", "official_channel", "location"], ...NODE },
  { id: "authorities", title: tr("copy.authorities_7ee1fcc", { lng: "en" }), types: ["authority", "legal_instrument"], ...NODE },
];

const GROUP_TITLE: Record<string, string> = {
  requirements: tr("copy.requirements_and_eligibility_rules_cb831d4", { lng: "en" }),
  channels: tr("copy.where_to_apply_and_jurisdictions_bd8e1d9", { lng: "en" }),
  authorities: tr("copy.authorities_and_laws_866a654", { lng: "en" }),
};

/** List-view groups (same buckets as the columns). */
export const GOVERNANCE_GROUPS: ExplorerGroup[] = GOVERNANCE_COLUMNS.map((c) => ({ id: c.id, title: GROUP_TITLE[c.id] ?? c.title }));

export type GovernanceFilter = "all" | "services" | "authorities" | "documents" | "requirements" | "channels";

export const GOVERNANCE_FILTERS: { value: GovernanceFilter; label: string }[] = [
  { value: "all", label: tr("copy.all_6a72085", { lng: "en" }) },
  { value: "services", label: tr("copy.services_5cbd584", { lng: "en" }) },
  { value: "authorities", label: tr("copy.authorities_7ee1fcc", { lng: "en" }) },
  { value: "documents", label: tr("copy.documents_687c828", { lng: "en" }) },
  { value: "requirements", label: tr("copy.requirements_09a428f", { lng: "en" }) },
  { value: "channels", label: tr("copy.where_to_apply_b48c089", { lng: "en" }) },
];

/** Edge look per relation: a CSS variant, an arrowhead, and whether it can carry an "either" label. */
const RELATION_VARIANT: Record<string, string> = {
  depends_on: "depends",
  requires: "requires",
  may_require: "may",
  produces: "produces",
  satisfied_by: "produces",
  applies_to: "applies",
};

export function relationVariant(relation: string): string {
  return RELATION_VARIANT[relation] ?? "quiet";
}

export function typeLabel(type: string): string {
  return GOVERNANCE_TYPE_LABEL[type] ?? humanize(type);
}

export function humanize(key: string): string {
  const text = key.replace(/[_.]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Short name an authority is known by: "ICP", "ADDED", "MoFA". */
export function acronymOf(label: string): string | null {
  const paren = label.match(/\(([^()]+)\)\s*$/);
  const inner = paren?.[1]?.trim();
  if (inner && /^[A-Za-z][A-Za-z&]{1,7}$/.test(inner) && /[A-Z].*[A-Z]/.test(inner)) return inner;
  const lead = label.match(/^([A-Z]{2,6})\b/);
  return lead ? lead[1]! : null;
}

/** The label without a trailing "(ACRONYM)", for when the acronym is shown on its own. */
export function withoutAcronym(label: string): string {
  const acronym = acronymOf(label);
  if (!acronym) return label;
  return label.replace(new RegExp(`\\s*\\(${acronym.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\)\\s*$`), "");
}

const VERB = /^(get your|get an|get a|get|issue an|issue a|register for|register your|register a|reserve a|submit an|submit a|create and verify your|open a|attest a|connect|sponsor a|find a|call an|exchange a|incorporate a)\s+/i;

/**
 * A shorter label for the zoomed-out map: services lose their leading verb ("Get your
 * residence visa" becomes "Residence visa") and long asides in brackets are dropped.
 */
export function shortLabel(node: Pick<KnowledgeNode, "label" | "type">): string {
  let text = node.label;
  if (node.type === "service" || node.type === "appointment") text = text.replace(VERB, "");
  text = text.replace(/\s*\(([^()]{13,})\)\s*$/, "");
  if (!text.trim()) return node.label;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function aliasesOf(node: KnowledgeNode): string[] {
  const raw = node.properties.aliases;
  return Array.isArray(raw) ? raw.filter((a): a is string => typeof a === "string") : [];
}

export function requiresUaePass(node: KnowledgeNode): boolean {
  return node.properties.requires_uae_pass === true;
}

export function isMapNode(node: KnowledgeNode): boolean {
  return !GOVERNANCE_SOURCE_TYPES.has(node.type);
}

export interface GovernanceMap {
  items: ExplorerItem[];
  edges: ExplorerEdge[];
  headers: ExplorerHeader[];
  bounds: Rect;
}

/** Lay out the rules (not the cited sources) as columns, ready for the explorer. */
export function buildGovernanceMap(graph: KnowledgeGraph, aspect: number): GovernanceMap {
  const nodes = graph.nodes.filter(isMapNode);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => e.relation !== "evidenced_by" && ids.has(e.source) && ids.has(e.target) && e.source !== e.target);
  const layout = columnLayout(
    nodes.map((n) => ({ id: n.id, type: n.type, label: n.label })),
    edges.map((e) => ({ id: e.id, source: e.source, target: e.target, relation: e.relation })),
    { columns: GOVERNANCE_COLUMNS, aspect, rowGap: 10, subColumnGap: 16, columnGap: 84, headerHeight: 52 },
  );
  const hub = GOVERNANCE_COLUMNS.find((c) => c.hub)!.id;
  const items: ExplorerItem[] = nodes.map((n) => {
    const group = layout.columnOf.get(n.id) ?? hub;
    return {
      id: n.id,
      key: n.key,
      label: n.label,
      type: n.type,
      typeLabel: typeLabel(n.type),
      group,
      summary: n.summary,
      aliases: aliasesOf(n),
      rect: layout.nodes.get(n.id)!,
      nodeType: "governance",
      extra: { acronym: n.type === "authority" ? acronymOf(n.label) : null, hub: group === hub, short: shortLabel(n) },
    };
  });
  const explorerEdges: ExplorerEdge[] = edges.map((e) => {
    const route = layout.edges.get(e.id)!;
    const relation = RELATION_LABEL[e.relation] ?? humanize(e.relation).toLowerCase();
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      relation: e.relation,
      text: e.anyOf ? `${relation} (either)` : relation,
      path: route.path,
      labelPoint: route.label,
      variant: relationVariant(e.relation),
      marker: e.relation === "depends_on" ? "ink" : null,
      pinnedLabel: e.anyOf ? "either" : null,
    };
  });
  const headers: ExplorerHeader[] = layout.columns.map((c) => ({ id: `header:${c.id}`, title: c.title, count: c.count, rect: c.header }));
  return { items, edges: explorerEdges, headers, bounds: layout.bounds };
}

/** Which list/column groups a filter keeps (the others are dimmed). */
export function filterGroups(filter: GovernanceFilter): Set<string> | null {
  return filter === "all" ? null : new Set([filter]);
}

// --- details panel -----------------------------------------------------------------------------

const OUTGOING: Record<string, string> = {
  depends_on: tr("copy.comes_after_4917032", { lng: "en" }),
  satisfied_by: tr("copy.either_of_these_counts_f7980fe", { lng: "en" }),
  requires: tr("copy.you_ll_need_713f5f1", { lng: "en" }),
  may_require: tr("copy.may_also_need_d0269c1", { lng: "en" }),
  provided_by: tr("copy.provided_by_ce84515", { lng: "en" }),
  available_at: tr("copy.where_to_apply_b48c089", { lng: "en" }),
  available_via: tr("copy.where_to_apply_b48c089", { lng: "en" }),
  located_in: tr("copy.located_in_179a181", { lng: "en" }),
  produces: tr("copy.gives_you_89916e0", { lng: "en" }),
  governed_by: tr("copy.governed_by_4d5f7d7", { lng: "en" }),
  provides: tr("copy.services_it_provides_cc8ed6c", { lng: "en" }),
  applies_to: tr("copy.applies_to_0c9d314", { lng: "en" }),
};

const INCOMING: Record<string, string> = {
  applies_to: tr("copy.eligibility_rules_bbb5780", { lng: "en" }),
  provides: tr("copy.provided_by_ce84515", { lng: "en" }),
  depends_on: tr("copy.unlocks_aecf18a", { lng: "en" }),
  requires: tr("copy.needed_for_78eaf20", { lng: "en" }),
  may_require: tr("copy.sometimes_needed_for_73c9664", { lng: "en" }),
  produces: tr("copy.where_you_get_it_fba5aab", { lng: "en" }),
  satisfied_by: tr("copy.counts_towards_43b80c9", { lng: "en" }),
  provided_by: tr("copy.services_it_provides_cc8ed6c", { lng: "en" }),
  available_at: tr("copy.what_you_can_do_here_facf040", { lng: "en" }),
  available_via: tr("copy.what_you_can_do_here_facf040", { lng: "en" }),
  located_in: tr("copy.located_here_6927aeb", { lng: "en" }),
  governed_by: tr("copy.governs_ad48ea8", { lng: "en" }),
};

/** Reading order of the groups: what comes first, what you need, who and where, what you get, what it leads to. */
const GROUP_ORDER = [
  tr("copy.comes_after_4917032", { lng: "en" }),
  tr("copy.either_of_these_counts_f7980fe", { lng: "en" }),
  tr("copy.eligibility_rules_bbb5780", { lng: "en" }),
  tr("copy.you_ll_need_713f5f1", { lng: "en" }),
  tr("copy.may_also_need_d0269c1", { lng: "en" }),
  tr("copy.provided_by_ce84515", { lng: "en" }),
  tr("copy.where_to_apply_b48c089", { lng: "en" }),
  tr("copy.located_in_179a181", { lng: "en" }),
  tr("copy.gives_you_89916e0", { lng: "en" }),
  tr("copy.where_you_get_it_fba5aab", { lng: "en" }),
  tr("copy.unlocks_aecf18a", { lng: "en" }),
  tr("copy.needed_for_78eaf20", { lng: "en" }),
  tr("copy.sometimes_needed_for_73c9664", { lng: "en" }),
  tr("copy.counts_towards_43b80c9", { lng: "en" }),
  tr("copy.services_it_provides_cc8ed6c", { lng: "en" }),
  tr("copy.what_you_can_do_here_facf040", { lng: "en" }),
  tr("copy.located_here_6927aeb", { lng: "en" }),
  tr("copy.applies_to_0c9d314", { lng: "en" }),
  tr("copy.governed_by_4d5f7d7", { lng: "en" }),
  tr("copy.governs_ad48ea8", { lng: "en" }),
];

export interface NeighbourGroup {
  title: string;
  items: { node: KnowledgeNode; edge: KnowledgeEdge; either: boolean }[];
}

/** A node's neighbours grouped by what the relation means from this node's point of view. */
export function groupNeighbours(nodeId: string, edges: KnowledgeEdge[], neighbours: KnowledgeNode[]): NeighbourGroup[] {
  const byId = new Map(neighbours.map((n) => [n.id, n]));
  const groups = new Map<string, NeighbourGroup>();
  for (const edge of edges) {
    if (edge.relation === "evidenced_by") continue;
    const outgoing = edge.source === nodeId;
    const other = byId.get(outgoing ? edge.target : edge.source);
    if (!other || !isMapNode(other) || other.id === nodeId) continue;
    const title = (outgoing ? OUTGOING : INCOMING)[edge.relation] ?? `${outgoing ? "" : tr("copy.linked_from_49e76c8")}${humanize(RELATION_LABEL[edge.relation] ?? edge.relation)}`;
    const group = groups.get(title) ?? { title, items: [] };
    if (!group.items.some((i) => i.node.id === other.id)) group.items.push({ node: other, edge, either: Boolean(edge.anyOf) });
    groups.set(title, group);
  }
  const rank = (title: string) => {
    const i = GROUP_ORDER.indexOf(title);
    return i < 0 ? GROUP_ORDER.length : i;
  };
  return [...groups.values()]
    .map((g) => ({ ...g, items: [...g.items].sort((a, b) => a.node.label.localeCompare(b.node.label)) }))
    .sort((a, b) => rank(a.title) - rank(b.title) || a.title.localeCompare(b.title));
}

// --- conditions ------------------------------------------------------------------------------------

export type ConditionText = { kind: "leaf"; text: string } | { kind: "any" | "all"; items: ConditionText[] };

/** Boolean facts read as sentences ("Unmarried"), not "Married: no". */
interface FactPhrase {
  label: string;
  unit?: "aed";
  yes?: string;
  no?: string;
}

const FACTS: Record<string, FactPhrase> = {
  "finance.monthly_income_aed": { label: tr("copy.monthly_income_ace11ec", { lng: "en" }), unit: "aed" },
  "company.investment_aed": { label: tr("copy.investment_in_the_company_75c820c", { lng: "en" }), unit: "aed" },
  "person.age": { label: tr("copy.age_ff9f1ff", { lng: "en" }) },
  "person.relationship_to_sponsor": { label: tr("copy.relationship_to_the_sponsor_ed4b7bb", { lng: "en" }) },
  "person.married": { label: tr("copy.married_c75a2b4", { lng: "en" }), yes: tr("copy.married_c75a2b4", { lng: "en" }), no: tr("copy.unmarried_1e78af5", { lng: "en" }) },
  "person.special_needs": { label: tr("copy.special_needs_2a55bdf", { lng: "en" }), yes: tr("copy.has_special_needs_1b47eb8", { lng: "en" }), no: tr("copy.no_special_needs_132761f", { lng: "en" }) },
  "housing.accommodation_provided": { label: tr("copy.accommodation_provided_ace12cf", { lng: "en" }), yes: tr("copy.accommodation_is_provided_by_the_employer_df7b59f", { lng: "en" }), no: tr("copy.no_accommodation_provided_76c3448", { lng: "en" }) },
  "company.has_resident_signatory": { label: tr("copy.resident_authorised_signatory_5545d12", { lng: "en" }), yes: tr("copy.the_company_has_a_uae_resident_authorised_signat_5fa2f1e", { lng: "en" }), no: tr("copy.no_uae_resident_authorised_signatory_a9e21c8", { lng: "en" }) },
  "driving.licence_exchangeable": { label: tr("copy.licence_can_be_exchanged_eb33613", { lng: "en" }), yes: tr("copy.your_licence_is_from_a_country_whose_licences_ca_67cfc21", { lng: "en" }), no: tr("copy.your_licence_can_t_be_exchanged_5a737ad", { lng: "en" }) },
  "documents.tenancy_contract_registered": { label: tr("copy.a_registered_tenancy_contract_tawtheeq_c968964", { lng: "en" }) },
  "documents.property_ownership_proof": { label: tr("copy.proof_of_owning_a_residence_49c5aa3", { lng: "en" }) },
  "company.jurisdiction": { label: tr("copy.company_jurisdiction_e8778c6", { lng: "en" }) },
  "company.legal_form": { label: tr("copy.company_legal_form_4ee4a12", { lng: "en" }) },
};

const VALUE_WORDS: Record<string, string> = { adgm: tr("copy.adgm_2f8e161", { lng: "en" }), llc: tr("copy.llc_f9ea624", { lng: "en" }), pjsc: tr("copy.pjsc_79447b7", { lng: "en" }), prjsc: tr("copy.prjsc_a8ca5ba", { lng: "en" }), limited_partnership: tr("copy.limited_partnership_b268478", { lng: "en" }) };

function phraseFor(fact: string): FactPhrase {
  if (FACTS[fact]) return FACTS[fact];
  const last = fact.split(".").pop() ?? fact;
  const aed = /_aed$/.test(last);
  return { label: humanize(last.replace(/_aed$/, "")), unit: aed ? "aed" : undefined };
}

function valueText(value: unknown, unit?: "aed"): string {
  if (typeof value === "number") return unit === "aed" ? formatCurrency(value) : formatNumber(value);
  if (typeof value === "string") return VALUE_WORDS[value] ?? value.replace(/_/g, " ");
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map((v) => valueText(v, unit)).join(" or ");
  return "";
}

/** A machine-readable eligibility rule as plain sentences. Null when it can't be read. */
export function describeCondition(raw: unknown): ConditionText | null {
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Record<string, unknown>;
  for (const kind of ["any", "all"] as const) {
    if (Array.isArray(c[kind])) {
      const items = (c[kind] as unknown[]).map(describeCondition).filter((i): i is ConditionText => i !== null);
      if (!items.length) return null;
      return items.length === 1 ? items[0]! : { kind, items };
    }
  }
  if (typeof c.fact !== "string" || typeof c.op !== "string") return null;
  const p = phraseFor(c.fact);
  const v = c.value;
  switch (c.op) {
    case "truthy":
      return { kind: "leaf", text: p.yes ?? p.label };
    case "falsy":
      return { kind: "leaf", text: p.no ?? `No ${p.label.toLowerCase()}` };
    case "eq":
      if (typeof v === "boolean") return { kind: "leaf", text: v ? (p.yes ?? `${p.label}: yes`) : (p.no ?? `${p.label}: no`) };
      return { kind: "leaf", text: `${p.label}: ${valueText(v, p.unit)}` };
    case "ne":
      return { kind: "leaf", text: tr("copy.v0_not_v1_08c29b9", { v0: p.label, v1: valueText(v, p.unit) }) };
    case "in":
      return { kind: "leaf", text: `${p.label}: ${valueText(v, p.unit)}` };
    case "gte":
      return { kind: "leaf", text: tr("copy.v0_at_least_v1_44891ef", { v0: p.label, v1: valueText(v, p.unit) }) };
    case "gt":
      return { kind: "leaf", text: tr("copy.v0_more_than_v1_de61057", { v0: p.label, v1: valueText(v, p.unit) }) };
    case "lte":
      return { kind: "leaf", text: tr("copy.v0_at_most_v1_1517ed3", { v0: p.label, v1: valueText(v, p.unit) }) };
    case "lt":
      return { kind: "leaf", text: tr("copy.v0_under_v1_a19c923", { v0: p.label, v1: valueText(v, p.unit) }) };
    default:
      return null;
  }
}

const SHOWN_ELSEWHERE = new Set(["aliases", "requires_uae_pass", "condition", "note", "informational", "verify_on_official_page"]);

/** Other simple properties worth showing, as label/value pairs ("Registered by: the landlord"). */
export function propertyFacts(node: KnowledgeNode): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = [];
  for (const [key, value] of Object.entries(node.properties)) {
    if (SHOWN_ELSEWHERE.has(key) || value === null || typeof value === "object") continue;
    if (key === "registered_by" && typeof value === "string") {
      out.push({ label: tr("copy.registered_by_8aeff6b"), value: `The ${value.replace(/_/g, " ")}` });
      continue;
    }
    const aed = /_aed$/.test(key);
    const label = humanize(key.replace(/_aed$/, ""));
    out.push({ label, value: typeof value === "number" && aed ? formatCurrency(value) : valueText(value) });
  }
  return out;
}
