import type { ConsentStatus } from "./common";

export interface Preferences {
  /** BCP-47 tag ADAPT converses in. */
  preferredLanguage: string;
  uiLocale: string;
  faithPersonalization: ConsentStatus;
  communityPersonalization: ConsentStatus;
  voiceTranscriptsRetained: boolean;
}

export type PreferencesUpdate = Partial<Preferences>;

export interface User {
  id: string;
  displayName: string | null;
  isDemo: boolean;
  preferences: Preferences;
  createdAt: string;
}

export type MoveType = "business" | "job" | "family" | "study" | "remote";
export type Household = "alone" | "spouse" | "spouse_children" | "children";
export type CompanyTiming = "now" | "later" | "none";
export type Jurisdiction = "mainland" | "adgm" | "undecided";
export type HousingPreference = "long_lease" | "short_stay_first";

/** Places of worship a user may choose to see. Only ever user-stated, after opt-in. */
export type FaithCommunity =
  | "islam"
  | "christianity"
  | "hinduism"
  | "sikhism"
  | "buddhism"
  | "judaism"
  | "all";

/**
 * What the user told ADAPT about their move during onboarding. Kept on the server
 * (or in memory by mock services); never persisted on the device.
 */
export interface MoveProfile {
  moveType: MoveType;
  /** Target arrival (ISO date) or null when the user is flexible. */
  arrivalDate: string | null;
  household: Household;
  childrenCount: number;
  companyTiming: CompanyTiming;
  jurisdiction: Jurisdiction;
  /** Languages the user chose to share, as BCP-47 tags. Voluntary. */
  languages: string[];
  housing: HousingPreference;
  monthlyHousingBudgetAed: number | null;
  /** Set only when faith personalisation is granted and the user picked one. */
  faith: FaithCommunity | null;
  /** Anything the user said or typed in their own words. */
  note: string;
}

export const MOVE_TYPE_LABEL: Record<MoveType, string> = {
  business: "Starting or moving a business",
  job: "Taking up a job",
  family: "Joining family",
  study: "Studying",
  remote: "Working remotely",
};

export const HOUSEHOLD_LABEL: Record<Household, string> = {
  alone: "Moving alone",
  spouse: "With my spouse",
  spouse_children: "With my spouse and children",
  children: "With my children",
};

export const COMPANY_TIMING_LABEL: Record<CompanyTiming, string> = {
  now: "Setting up a company now",
  later: "Setting up a company later",
  none: "No company",
};

export const HOUSING_LABEL: Record<HousingPreference, string> = {
  long_lease: "Sign a long-term lease",
  short_stay_first: "Short stay first, then a lease",
};

export function hasSpouse(household: Household): boolean {
  return household === "spouse" || household === "spouse_children";
}

export function hasChildren(household: Household): boolean {
  return household === "spouse_children" || household === "children";
}
