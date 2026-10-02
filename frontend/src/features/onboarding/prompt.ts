import { tr } from "@/i18n";
import {
  COMPANY_TIMING_LABEL,
  HOUSEHOLD_LABEL,
  MOVE_TYPE_LABEL,
  type MoveProfile,
} from "@/domain/profile";
import { formatDate } from "@/lib/format";
import { languageName } from "@/lib/languages";

/**
 * The request sent to the journey agent: the user's own words first, then a plain summary
 * of their answers, so the agent sees both even if one is incomplete.
 */
export function composePrompt(profile: MoveProfile, note: string): string {
  const parts: string[] = [];
  if (note.trim()) parts.push(note.trim());
  const facts = [
    `${MOVE_TYPE_LABEL[profile.moveType]}.`,
    profile.arrivalDate ? `I plan to arrive in Abu Dhabi on ${formatDate(profile.arrivalDate)}.` : "My arrival date is flexible.",
    `${HOUSEHOLD_LABEL[profile.household]}${profile.childrenCount > 0 ? ` (${profile.childrenCount} ${profile.childrenCount === 1 ? "child" : "children"})` : ""}.`,
    profile.companyTiming === "none" ? tr("copy.i_m_not_starting_a_company_4627f0c") : `${COMPANY_TIMING_LABEL[profile.companyTiming]}.`,
    profile.languages.length ? `I speak ${profile.languages.map(languageName).join(", ")}.` : null,
  ].filter(Boolean);
  parts.push(facts.join(" "));
  return parts.join("\n\n");
}

export const DEFAULT_PROFILE: MoveProfile = {
  moveType: "business",
  arrivalDate: null,
  household: "alone",
  childrenCount: 0,
  companyTiming: "now",
  jurisdiction: "undecided",
  languages: [],
  housing: "long_lease",
  monthlyHousingBudgetAed: null,
  faith: null,
  note: "",
};
