import { describe, expect, it } from "vitest";
import { composePrompt, DEFAULT_PROFILE } from "./prompt";

describe("composePrompt", () => {
  it("puts the user's own words first, then a summary of their answers", () => {
    const prompt = composePrompt(
      { ...DEFAULT_PROFILE, household: "spouse_children", childrenCount: 2, arrivalDate: "2026-11-12", languages: ["en", "ar"] },
      "  We're relocating our design studio.  ",
    );
    const [note, summary] = prompt.split("\n\n");
    expect(note).toBe("We're relocating our design studio.");
    expect(summary).toContain("Starting or moving a business.");
    expect(summary).toContain("With my spouse and children (2 children).");
    expect(summary).toContain("12 Nov 2026");
    expect(summary).toContain("I speak English, Arabic.");
  });

  it("describes flexible arrival and no company plainly", () => {
    const prompt = composePrompt({ ...DEFAULT_PROFILE, moveType: "job", companyTiming: "none" }, "");
    expect(prompt).toContain("My arrival date is flexible.");
    expect(prompt).toContain("I'm not starting a company.");
    expect(prompt).not.toContain("\n\n");
  });
});
