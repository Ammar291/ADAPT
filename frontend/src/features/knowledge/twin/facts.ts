import { formatNumber } from "@/lib/format";
import { tr } from "@/i18n";
/**
 * How a private twin fact reads in the details panel: its label, value, confidence in words,
 * and whether it looks like a document number that should stay masked until asked.
 */
import { FACT_SOURCE_LABEL, type TwinFact } from "@/domain/graph";
import { formatDate } from "@/lib/format";

const FACT_LABEL: Record<string, string> = {
  move_type: tr("copy.type_of_move_402d09c", { lng: "en" }),
  household: tr("copy.household_52996fa", { lng: "en" }),
  arrival_date: tr("copy.arrival_date_f156feb", { lng: "en" }),
  relationship: tr("copy.relationship_9b4a86c", { lng: "en" }),
  timing: tr("copy.when_769bb19", { lng: "en" }),
  jurisdiction: tr("copy.jurisdiction_5d1cc3c", { lng: "en" }),
  status: "Status",
  preference: tr("copy.preference_97d9b28", { lng: "en" }),
  budget: tr("copy.budget_7aeba4c", { lng: "en" }),
  languages: tr("copy.languages_db07be1", { lng: "en" }),
  faith: tr("copy.faith_a00bb6a", { lng: "en" }),
  date: tr("copy.date_eb9a4bc", { lng: "en" }),
  surname: tr("copy.surname_77dfca2", { lng: "en" }),
  given_names: tr("copy.given_names_757cdc8", { lng: "en" }),
  nationality: tr("copy.nationality_1969ead", { lng: "en" }),
  date_of_birth: tr("copy.date_of_birth_9518425", { lng: "en" }),
  passport_number: tr("copy.passport_number_6d45a37", { lng: "en" }),
  date_of_expiry: tr("copy.expiry_date_6b440cd", { lng: "en" }),
  issuing_authority: tr("copy.issuing_authority_6a3ec54", { lng: "en" }),
  party_1: tr("copy.first_party_38cf35f", { lng: "en" }),
  party_2: tr("copy.second_party_4cea090", { lng: "en" }),
  date_of_marriage: tr("copy.date_of_marriage_7792c43", { lng: "en" }),
  place_of_marriage: tr("copy.place_of_marriage_4a83269", { lng: "en" }),
  certificate_number: tr("copy.certificate_number_1cdebe3", { lng: "en" }),
  home_attestation: tr("copy.home_country_attestation_7cc08ee", { lng: "en" }),
  document_type: tr("copy.document_type_300b6ef", { lng: "en" }),
  background: tr("copy.background_64dd60f", { lng: "en" }),
  meets_specification: tr("copy.meets_the_icp_photo_specification_8e0acd3", { lng: "en" }),
};

export function factLabel(key: string): string {
  if (FACT_LABEL[key]) return FACT_LABEL[key];
  const text = key.replace(/[_.]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export type ConfidenceLevel = "high" | "medium" | "low";

export function confidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.85) return "high";
  if (confidence >= 0.6) return "medium";
  return "low";
}

export function confidenceWords(confidence: number): string {
  return { high: tr("copy.high_confidence_6c2943a"), medium: tr("copy.medium_confidence_156b5ba"), low: tr("copy.low_confidence_99d4cea") }[confidenceLevel(confidence)];
}

export function sourceWords(fact: TwinFact): string {
  return FACT_SOURCE_LABEL[fact.source] ?? tr("copy.adapt_2e26648");
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:?\d{2})?)?$/;
const NUMBER_KEY = /(^|_)(number|no|num|id|reference|ref|passport|licence|license|permit|emirates_id|iban|account)($|_)/i;

/** Already masked upstream (e.g. "•••• 1937"): there is nothing more to reveal. */
export function isMasked(value: unknown): boolean {
  return typeof value === "string" && /[•*]{3,}/.test(value);
}

/**
 * Whether a value looks like a document or account number, so it is masked by default:
 * a key that names a number, or a value that is mostly an identifier with 4+ digits.
 */
export function looksLikeDocumentNumber(key: string, value: unknown): boolean {
  if (typeof value !== "string" && typeof value !== "number") return false;
  const text = String(value).trim();
  if (!text || ISO_DATE.test(text) || isMasked(text)) return false;
  const digits = (text.match(/\d/g) ?? []).length;
  if (NUMBER_KEY.test(key) && digits >= 3) return true;
  return /^[A-Z]{0,4}[-\s]?[0-9][0-9A-Z\s-]{4,}$/i.test(text) && digits >= 5 && !/\s(aed|month|year)/i.test(text);
}

/** "•••• 0847": keeps the last four characters so people can still tell documents apart. */
export function maskValue(value: string): string {
  const compact = value.replace(/\s+/g, "");
  return `•••• ${compact.slice(-4)}`;
}

/** A fact value as text: dates formatted, lists joined, yes/no for booleans. */
export function formatFactValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return tr("copy.not_recorded_305cc36");
  if (typeof value === "boolean") return value ? tr("copy.yes_5397e05") : tr("copy.no_816c52f");
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return ISO_DATE.test(value) ? formatDate(value) || value : value;
  if (Array.isArray(value)) return value.map(formatFactValue).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
      .map(([k, v]) => `${factLabel(k)}: ${formatFactValue(v)}`)
      .join("; ");
  }
  return String(value);
}

export interface FactRow {
  key: string;
  label: string;
  value: string;
  /** Value is hidden until the person asks to see it. */
  sensitive: boolean;
  /** Masked before it reached the browser; cannot be revealed here. */
  masked: boolean;
  source: string;
  confidence: string;
  confidenceLevel: ConfidenceLevel;
  confirmed: boolean;
  observedAt: string | null;
}

export function factRows(facts: Record<string, TwinFact>): FactRow[] {
  return Object.entries(facts).map(([key, fact]) => ({
    key,
    label: factLabel(key),
    value: formatFactValue(fact.value),
    sensitive: looksLikeDocumentNumber(key, fact.value),
    masked: isMasked(fact.value),
    source: sourceWords(fact),
    confidence: confidenceWords(fact.confidence),
    confidenceLevel: confidenceLevel(fact.confidence),
    confirmed: fact.confirmedByUser,
    observedAt: fact.observedAt,
  }));
}
