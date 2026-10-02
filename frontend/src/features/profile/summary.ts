import { formatCurrency } from "@/lib/format";
import { tr } from "@/i18n";
/**
 * Pure summaries for the Profile screen: the user's move as readable rows, and what ADAPT
 * holds in their digital twin. No I/O.
 */
import type { FactSource, KnowledgeGraph } from "@/domain/graph";
import {
  COMPANY_TIMING_LABEL,
  hasChildren,
  HOUSEHOLD_LABEL,
  HOUSING_LABEL,
  MOVE_TYPE_LABEL,
  type FaithCommunity,
  type Jurisdiction,
  type MoveProfile,
} from "@/domain/profile";
import { daysUntil, formatDate } from "@/lib/format";
import { languageName } from "@/lib/languages";

export interface MoveRow {
  key: "moveType" | "arrival" | "household" | "company" | "languages" | "housing" | "faith";
  label: string;
  value: string;
  /** A second, quieter line. */
  detail: string | null;
}

export const FAITH_LABEL: Record<FaithCommunity, string> = {
  all: tr("copy.all_faiths_f379537", { lng: "en" }),
  islam: tr("copy.islam_4f910da", { lng: "en" }),
  christianity: tr("copy.christianity_59d48ff", { lng: "en" }),
  hinduism: tr("copy.hinduism_df9d0c6", { lng: "en" }),
  sikhism: tr("copy.sikhism_043d45a", { lng: "en" }),
  buddhism: tr("copy.buddhism_6eb15e6", { lng: "en" }),
  judaism: tr("copy.judaism_5439569", { lng: "en" }),
};

const JURISDICTION_DETAIL: Record<Jurisdiction, string> = {
  mainland: tr("copy.abu_dhabi_mainland_5e66a8b", { lng: "en" }),
  adgm: tr("copy.adgm_2f8e161", { lng: "en" }),
  undecided: tr("copy.mainland_or_adgm_not_decided_yet_5929e11", { lng: "en" }),
};

function arrivalDetail(arrivalDate: string, now: Date): string | null {
  const days = daysUntil(arrivalDate, now);
  if (days === null) return null;
  if (days > 1) return tr("copy.in_v0_days_7fc1a8b", { v0: days });
  if (days === 1) return tr("copy.tomorrow_1948bf2");
  if (days === 0) return tr("copy.today_24345a1");
  return null;
}

/** The move as label/value rows, in the order people think about it. */
export function moveRows(profile: MoveProfile, now = new Date()): MoveRow[] {
  const rows: MoveRow[] = [
    { key: "moveType", label: tr("copy.reason_for_moving_cb0c314"), value: MOVE_TYPE_LABEL[profile.moveType], detail: null },
    {
      key: "arrival",
      label: tr("copy.arrival_dc21d2b"),
      value: profile.arrivalDate ? formatDate(profile.arrivalDate) : "Flexible",
      detail: profile.arrivalDate ? arrivalDetail(profile.arrivalDate, now) : tr("copy.no_fixed_date_yet_bfed93b"),
    },
    {
      key: "household",
      label: tr("copy.household_52996fa"),
      value: HOUSEHOLD_LABEL[profile.household],
      detail: hasChildren(profile.household)
        ? `${profile.childrenCount} ${profile.childrenCount === 1 ? "child" : "children"}`
        : null,
    },
    {
      key: "company",
      label: tr("copy.company_7a19949"),
      value: COMPANY_TIMING_LABEL[profile.companyTiming],
      detail: profile.companyTiming === "none" ? null : JURISDICTION_DETAIL[profile.jurisdiction],
    },
    {
      key: "languages",
      label: tr("copy.languages_db07be1"),
      value: profile.languages.length ? profile.languages.map(languageName).join(", ") : "Not shared",
      detail: null,
    },
    {
      key: "housing",
      label: tr("copy.housing_0ebae7e"),
      value: HOUSING_LABEL[profile.housing],
      detail: profile.monthlyHousingBudgetAed
        ? tr("format.budgetUpTo", { amount: formatCurrency(profile.monthlyHousingBudgetAed) })
        : null,
    },
  ];
  if (profile.faith) {
    rows.push({ key: "faith", label: tr("copy.places_of_worship_a018ec3"), value: FAITH_LABEL[profile.faith], detail: tr("copy.shown_because_you_chose_to_share_it_655136e") });
  }
  return rows;
}

export interface TwinSummary {
  /** People, goals, documents and preferences in the twin. */
  items: number;
  facts: number;
  bySource: Record<FactSource, number>;
}

/** Counts what the user's private digital twin holds, by where each fact came from. */
export function summariseTwin(graph: KnowledgeGraph): TwinSummary {
  const bySource: Record<FactSource, number> = { user_stated: 0, document_extracted: 0, inferred: 0, system: 0 };
  let facts = 0;
  for (const node of graph.nodes) {
    for (const fact of Object.values(node.facts)) {
      bySource[fact.source] += 1;
      facts += 1;
    }
  }
  return { items: graph.nodes.length, facts, bySource };
}

/** "9 you told ADAPT, 3 read from your documents": the non-zero sources, plainly. */
export function describeFactSources(summary: TwinSummary): string {
  const parts = [
    summary.bySource.user_stated ? `${summary.bySource.user_stated} you told ADAPT` : null,
    summary.bySource.document_extracted ? `${summary.bySource.document_extracted} read from your documents` : null,
    summary.bySource.inferred ? `${summary.bySource.inferred} inferred by ADAPT` : null,
    summary.bySource.system ? `${summary.bySource.system} set by ADAPT` : null,
  ].filter((p): p is string => p !== null);
  return parts.join(", ");
}

export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}
