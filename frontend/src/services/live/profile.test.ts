import { describe, expect, it } from "vitest";
import type { MoveProfile } from "@/domain/profile";
import { toMoveProfile, toOnboardingRequest } from "./profile";

const profile: MoveProfile = {
  moveType: "business",
  arrivalDate: "2026-11-12",
  household: "spouse_children",
  childrenCount: 2,
  companyTiming: "now",
  jurisdiction: "undecided",
  languages: ["en", "ar"],
  housing: "long_lease",
  monthlyHousingBudgetAed: 12000,
  faith: null,
  note: "",
};

describe("live profile mapping", () => {
  it("sends household members, goals and planning assumptions", () => {
    const body = toOnboardingRequest(profile);
    expect(body.profile.persona).toBe("founder");
    expect(body.household.map((m: { relationship: string }) => m.relationship)).toEqual(["spouse", "child", "child"]);
    expect(body.goals.map((g: { goal_type: string }) => g.goal_type)).toEqual(
      expect.arrayContaining(["establish_company", "residency", "sponsor_family", "schooling"]),
    );
    expect(body.preferences).not.toContainEqual(expect.objectContaining({ category: "faith" }));
  });

  it("round-trips through the profile response", () => {
    const body = toOnboardingRequest(profile);
    const back = toMoveProfile({ profile: { ...body.profile, onboarding_completed_at: "2026-09-29T10:00:00Z" }, household: body.household, preferences: body.preferences });
    expect(back).toEqual(profile);
  });

  it("returns null before onboarding", () => {
    expect(toMoveProfile({ profile: { persona: null, onboarding_completed_at: null } })).toBeNull();
  });
});
