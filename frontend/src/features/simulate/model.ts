import { formatCurrency } from "@/lib/format";
import { tr } from "@/i18n";
/**
 * Pure model for the What if? controls: the variables a person can change, what differs
 * from their current plan, presets, and plain labels for assumption values.
 */
import { ASSUMPTION, type Journey } from "@/domain/journey";
import {
  COMPANY_TIMING_LABEL,
  hasChildren,
  HOUSEHOLD_LABEL,
  HOUSING_LABEL,
  type CompanyTiming,
  type Household,
  type HousingPreference,
  type Jurisdiction,
} from "@/domain/profile";
import type { AssumptionChange } from "@/domain/simulate";
import { formatDate } from "@/lib/format";

export interface Draft {
  household: Household;
  childrenCount: number;
  companyTiming: CompanyTiming;
  /** Where the company is licensed. */
  jurisdiction: Jurisdiction;
  /** ISO date, or null when flexible. */
  arrivalDate: string | null;
  /** Monthly housing budget in AED, or null when not set. */
  budget: number | null;
  housing: HousingPreference;
}

export type VariableKey = keyof Draft;

export const VARIABLE_ASSUMPTION: Record<VariableKey, string> = {
  household: ASSUMPTION.household,
  childrenCount: ASSUMPTION.children,
  companyTiming: ASSUMPTION.companyTiming,
  jurisdiction: ASSUMPTION.jurisdiction,
  arrivalDate: ASSUMPTION.arrivalDate,
  budget: ASSUMPTION.budget,
  housing: ASSUMPTION.housing,
};

export const VARIABLE_LABEL: Record<VariableKey, string> = {
  household: tr("copy.who_s_moving_b17d93f", { lng: "en" }),
  childrenCount: tr("copy.children_dcf7519", { lng: "en" }),
  companyTiming: tr("copy.your_company_3f7a84e", { lng: "en" }),
  jurisdiction: tr("copy.where_your_company_is_licensed_3472e80", { lng: "en" }),
  arrivalDate: tr("copy.target_arrival_345b033", { lng: "en" }),
  budget: tr("copy.monthly_housing_budget_f5ba7e2", { lng: "en" }),
  housing: tr("copy.housing_0ebae7e", { lng: "en" }),
};

const ORDER: VariableKey[] = ["household", "childrenCount", "companyTiming", "jurisdiction", "arrivalDate", "budget", "housing"];

export const JURISDICTION_LABEL: Record<Jurisdiction, string> = {
  mainland: tr("copy.abu_dhabi_mainland_5e66a8b", { lng: "en" }),
  adgm: tr("copy.adgm_2f8e161", { lng: "en" }),
  undecided: tr("copy.not_decided_yet_78f8d7f", { lng: "en" }),
};

/** The variables a simulation can take, as the assumption keys a SimulationService reports. */
export function variablesFor(assumptionKeys: readonly string[]): Set<VariableKey> {
  return new Set(ORDER.filter((key) => assumptionKeys.includes(VARIABLE_ASSUMPTION[key])));
}

export const BUDGET = { min: 3000, max: 30000, step: 500 } as const;

const HOUSEHOLDS = Object.keys(HOUSEHOLD_LABEL) as Household[];
const TIMINGS = Object.keys(COMPANY_TIMING_LABEL) as CompanyTiming[];
const HOUSINGS = Object.keys(HOUSING_LABEL) as HousingPreference[];
const JURISDICTIONS: Jurisdiction[] = ["mainland", "adgm", "undecided"];

function pick<T extends string>(value: unknown, allowed: T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** The current plan's answers, read from its assumptions. */
export function draftFromJourney(journey: Pick<Journey, "assumptions">): Draft {
  const get = (key: string) => journey.assumptions.find((a) => a.key === key)?.value;
  const children = Number(get(ASSUMPTION.children));
  const budget = get(ASSUMPTION.budget);
  const arrival = get(ASSUMPTION.arrivalDate);
  return {
    household: pick(get(ASSUMPTION.household), HOUSEHOLDS, "alone"),
    childrenCount: Number.isFinite(children) && children > 0 ? Math.round(children) : 0,
    companyTiming: pick(get(ASSUMPTION.companyTiming), TIMINGS, "none"),
    jurisdiction: pick(get(ASSUMPTION.jurisdiction), JURISDICTIONS, "undecided"),
    arrivalDate: typeof arrival === "string" && arrival ? arrival.slice(0, 10) : null,
    budget: typeof budget === "number" && Number.isFinite(budget) ? budget : null,
    housing: pick(get(ASSUMPTION.housing), HOUSINGS, "long_lease"),
  };
}

/** Children only count when the household includes them. */
function effective(draft: Draft): Draft {
  return hasChildren(draft.household) ? { ...draft, childrenCount: Math.max(1, draft.childrenCount) } : { ...draft, childrenCount: 0 };
}

/**
 * Variables that differ from the current plan, in display order. The number of children
 * only counts while the new household includes children (the household change says the rest).
 */
export function changedKeys(base: Draft, draft: Draft): VariableKey[] {
  const a = effective(base);
  const b = effective(draft);
  return ORDER.filter((key) => (key === "childrenCount" && !hasChildren(draft.household) ? false : a[key] !== b[key]));
}

/** Only the modified assumptions, as the simulation API expects them. */
export function changesBetween(base: Draft, draft: Draft): AssumptionChange[] {
  const b = effective(draft);
  return changedKeys(base, draft).map((key) => ({ key: VARIABLE_ASSUMPTION[key], value: b[key] }));
}

export function sameChanges(a: AssumptionChange[] | undefined, b: AssumptionChange[]): boolean {
  if (!a || a.length !== b.length) return false;
  return a.every((change, i) => change.key === b[i]!.key && change.value === b[i]!.value);
}

// --- dates --------------------------------------------------------------------------------------------

export function isoDay(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Same day of the month, n months on (clamped to the month's last day). */
export function addMonths(iso: string, months: number): string {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  const target = new Date(y, m - 1 + months, 1);
  const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(d, last));
  return isoDay(target);
}

// --- presets ----------------------------------------------------------------------------------------------

export type PresetId = "alone_first" | "company_later" | "in_adgm" | "arrive_later" | "short_stay";

export interface Preset {
  id: PresetId;
  label: string;
  description: string;
  key: VariableKey;
  /** The value this preset sets, derived from the current plan so it never compounds. */
  value: (base: Draft, today: Date) => Draft[VariableKey];
}

export const PRESETS: Preset[] = [
  { id: "alone_first", label: tr("copy.move_alone_first_234184e", { lng: "en" }), description: tr("copy.family_joins_later_bc26b5a", { lng: "en" }), key: "household", value: () => "alone" },
  { id: "company_later", label: tr("copy.start_the_company_later_9a17405", { lng: "en" }), description: tr("copy.arrive_on_another_route_first_e309b15", { lng: "en" }), key: "companyTiming", value: () => "later" },
  { id: "in_adgm", label: tr("copy.set_up_in_adgm_9951415", { lng: "en" }), description: tr("copy.license_the_company_in_abu_dhabi_global_market_fb248e2", { lng: "en" }), key: "jurisdiction", value: () => "adgm" },
  {
    id: "arrive_later",
    label: tr("copy.arrive_a_month_later_34be9d0", { lng: "en" }),
    description: tr("copy.more_time_before_you_land_4c1bbb2", { lng: "en" }),
    key: "arrivalDate",
    value: (base, today) => addMonths(base.arrivalDate ?? isoDay(new Date(today.getTime() + 60 * 86_400_000)), 1),
  },
  { id: "short_stay", label: tr("copy.short_stay_first_c975bfa", { lng: "en" }), description: tr("copy.then_sign_a_lease_07a8fa5", { lng: "en" }), key: "housing", value: () => "short_stay_first" },
];

/** A preset is offered only when it would change something. */
export function presetAvailable(base: Draft, preset: Preset, today = new Date()): boolean {
  return base[preset.key] !== preset.value(base, today);
}

export function presetActive(base: Draft, draft: Draft, preset: Preset, today = new Date()): boolean {
  return presetAvailable(base, preset, today) && draft[preset.key] === preset.value(base, today);
}

/** Applies a preset on top of the draft; applying an active preset again undoes it. */
export function togglePreset(base: Draft, draft: Draft, preset: Preset, today = new Date()): Draft {
  const on = presetActive(base, draft, preset, today);
  return { ...draft, [preset.key]: on ? base[preset.key] : preset.value(base, today) };
}

// --- labels -------------------------------------------------------------------------------------------------

export function formatBudget(value: number | null): string {
  return value === null ? tr("copy.not_set_93039e6") : tr("format.monthly", { amount: formatCurrency(value) });
}

/** A variable's value in plain words. */
export function variableValueLabel(key: VariableKey, draft: Draft): string {
  switch (key) {
    case "household":
      return HOUSEHOLD_LABEL[draft.household];
    case "childrenCount":
      return `${draft.childrenCount} ${draft.childrenCount === 1 ? "child" : "children"}`;
    case "companyTiming":
      return COMPANY_TIMING_LABEL[draft.companyTiming];
    case "jurisdiction":
      return JURISDICTION_LABEL[draft.jurisdiction];
    case "arrivalDate":
      return draft.arrivalDate ? formatDate(draft.arrivalDate) : tr("copy.flexible_8bb749a");
    case "budget":
      return formatBudget(draft.budget);
    case "housing":
      return HOUSING_LABEL[draft.housing];
  }
}

const ASSUMPTION_NAME: Record<string, string> = Object.fromEntries(
  (Object.keys(VARIABLE_ASSUMPTION) as VariableKey[]).map((key) => [VARIABLE_ASSUMPTION[key], VARIABLE_LABEL[key]]),
);

/** The name of an assumption, e.g. "Who's moving" for `household.composition`. */
export function assumptionName(key: string, fallback: string): string {
  return ASSUMPTION_NAME[key] ?? fallback;
}

/**
 * A simulated change's from/to value (sent as plain strings) in plain words:
 * "spouse" becomes "With my spouse", "12000" becomes "AED 12,000 a month".
 */
export function assumptionValueLabel(key: string, raw: string): string {
  if (raw === "" || raw === "null" || raw === "not set" || raw === "undefined") {
    return key === ASSUMPTION.arrivalDate ? tr("copy.flexible_8bb749a") : tr("copy.not_set_93039e6");
  }
  switch (key) {
    case ASSUMPTION.household:
      return HOUSEHOLD_LABEL[raw as Household] ?? raw;
    case ASSUMPTION.companyTiming:
      return COMPANY_TIMING_LABEL[raw as CompanyTiming] ?? raw;
    case ASSUMPTION.jurisdiction:
      return JURISDICTION_LABEL[raw as Jurisdiction] ?? raw;
    case ASSUMPTION.housing:
      return HOUSING_LABEL[raw as HousingPreference] ?? raw;
    case ASSUMPTION.budget: {
      const n = Number(raw);
      return Number.isFinite(n) ? formatBudget(n) : raw;
    }
    case ASSUMPTION.arrivalDate:
      return formatDate(raw) || raw;
    case ASSUMPTION.children: {
      const n = Number(raw);
      return Number.isFinite(n) ? `${n} ${n === 1 ? "child" : "children"}` : raw;
    }
    default:
      return raw;
  }
}
