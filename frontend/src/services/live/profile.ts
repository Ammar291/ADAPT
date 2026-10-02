/**
 * Live profile adapter: onboarding answers ↔ `/onboarding/profile` and `/profile`.
 * The journey agent plans from the saved profile, so onboarding saves it before starting.
 */
import { ASSUMPTION } from "@/domain/journey";
import { hasChildren, hasSpouse, type Household, type MoveProfile, type MoveType } from "@/domain/profile";
import { api } from "@/lib/api/client";
import type { ProfileService } from "../types";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const profilePaths = { save: "/onboarding/profile", get: "/profile" } as const;

const PERSONA: Record<MoveType, string> = { business: "founder", job: "employee", family: "family", study: "student", remote: "other" };
const MOVE_TYPE: Record<string, MoveType> = { founder: "business", investor: "business", employee: "job", family: "family", student: "study" };

export function toOnboardingRequest(profile: MoveProfile): Raw {
  const household: Raw[] = [];
  if (hasSpouse(profile.household)) household.push({ relationship: "spouse", name: "My spouse", relocation_plan: "with_user", needs_sponsorship: true });
  if (hasChildren(profile.household)) {
    for (let i = 1; i <= Math.max(1, profile.childrenCount); i++) {
      household.push({ relationship: "child", name: profile.childrenCount > 1 ? `Child ${i}` : "My child", relocation_plan: "with_user", needs_sponsorship: true });
    }
  }
  const goals: Raw[] = [{ goal_type: "residency" }, { goal_type: "find_housing" }, { goal_type: "community", priority: "low" }];
  if (profile.companyTiming !== "none") goals.unshift({ goal_type: "establish_company", priority: profile.companyTiming === "now" ? "high" : "low" });
  if (household.length) goals.push({ goal_type: "sponsor_family", priority: "high" });
  if (hasChildren(profile.household)) goals.push({ goal_type: "schooling" });

  const preferences: Raw[] = [{ category: "housing", key: "preference", value: profile.housing }];
  if (profile.monthlyHousingBudgetAed !== null) preferences.push({ category: "budget", key: "monthly_housing_aed", value: profile.monthlyHousingBudgetAed });
  if (profile.faith) preferences.push({ category: "faith", key: "places_of_worship", value: profile.faith });

  return {
    profile: {
      persona: PERSONA[profile.moveType],
      arrival_date: profile.arrivalDate,
      languages: profile.languages,
      target_city: "Abu Dhabi",
      assumptions: {
        [ASSUMPTION.moveType]: profile.moveType,
        [ASSUMPTION.household]: profile.household,
        [ASSUMPTION.children]: profile.childrenCount,
        [ASSUMPTION.companyTiming]: profile.companyTiming,
        [ASSUMPTION.jurisdiction]: profile.jurisdiction,
        [ASSUMPTION.housing]: profile.housing,
        [ASSUMPTION.budget]: profile.monthlyHousingBudgetAed,
      },
    },
    household,
    goals,
    preferences,
  };
}

export function toMoveProfile(raw: Raw): MoveProfile | null {
  const p = (raw.profile ?? {}) as Raw;
  if (!p.onboarding_completed_at && !p.persona) return null;
  const a = (p.assumptions ?? {}) as Raw;
  const members = (raw.household ?? []) as Raw[];
  const spouse = members.some((m) => m.relationship === "spouse");
  const children = members.filter((m) => m.relationship === "child").length;
  const household: Household = (a[ASSUMPTION.household] as Household) ?? (spouse ? (children ? "spouse_children" : "spouse") : children ? "children" : "alone");
  const pref = (category: string) => ((raw.preferences ?? []) as Raw[]).find((x) => x.category === category)?.value;
  return {
    moveType: (a[ASSUMPTION.moveType] as MoveType) ?? MOVE_TYPE[p.persona] ?? "business",
    arrivalDate: p.arrival_date ?? null,
    household,
    childrenCount: (a[ASSUMPTION.children] as number) ?? children,
    companyTiming: a[ASSUMPTION.companyTiming] ?? (p.persona === "founder" ? "now" : "none"),
    jurisdiction: a[ASSUMPTION.jurisdiction] ?? "undecided",
    languages: p.languages ?? [],
    housing: a[ASSUMPTION.housing] ?? pref("housing") ?? "long_lease",
    monthlyHousingBudgetAed: a[ASSUMPTION.budget] ?? pref("budget") ?? null,
    faith: pref("faith") ?? null,
    note: "",
  };
}

export const liveProfile: ProfileService = {
  async get(signal) {
    return toMoveProfile(await api.get<Raw>(profilePaths.get, { signal }));
  },
  async save(profile) {
    const saved = await api.post<Raw>(profilePaths.save, toOnboardingRequest(profile));
    return toMoveProfile(saved) ?? profile;
  },
};
