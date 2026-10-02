import { describe, expect, it } from "vitest";
import { allLanguages } from "@/lib/languages";
import { COMMUNITY_STATUS, consentValue, FAITH_STATUS, languageOptions, optionLabel, suggestedLanguages, tagLabel } from "./preferences";

describe("languageOptions", () => {
  it("offers every language the browser can name, not a shortlist", () => {
    const options = languageOptions("en");
    const distinctNames = new Set(allLanguages().map((l) => optionLabel(l))).size;
    expect(options.length).toBe(distinctNames);
    expect(options.length).toBeGreaterThan(150);
    expect(options.map((o) => o.value)).toContain("tl");
    expect(options.map((o) => o.value)).toContain("ml");
  });

  it("shows each language's own name next to its English name", () => {
    const arabic = languageOptions("en").find((o) => o.value === "ar");
    expect(arabic?.label).toBe("Arabic (العربية)");
    expect(languageOptions("en").find((o) => o.value === "en")?.label).toBe("English");
  });

  it("keeps a regional preference selectable", () => {
    const options = languageOptions("en-GB");
    const regional = options.find((o) => o.value === "en-GB");
    expect(regional?.label).toBe("British English");
    expect(options.length).toBe(languageOptions("en").length + 1);
    const labels = options.map((o) => o.label);
    expect(labels).toEqual([...labels].sort((a, b) => a.localeCompare(b)));
  });

  it("lists a name only once, unless the duplicate is the current preference", () => {
    const languages = [
      { code: "ak", name: "Akan", autonym: "Akan" },
      { code: "tw", name: "Akan", autonym: "Akan" },
      { code: "en", name: "English", autonym: "English" },
    ];
    expect(languageOptions("en", languages).map((o) => o.value)).toEqual(["ak", "en"]);
    expect(languageOptions("tw", languages).map((o) => o.value)).toEqual(["ak", "tw", "en"]);
    const labels = languageOptions("en").map((o) => o.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("puts the browser's own languages first when they are known", () => {
    const options = languageOptions("en");
    expect(suggestedLanguages(["fr", "xx", "ar"], options).map((o) => o.value)).toEqual(["fr", "ar"]);
    expect(suggestedLanguages([], options)).toEqual([]);
  });
});

describe("labels", () => {
  it("formats names and tags", () => {
    expect(optionLabel({ name: "Hindi", autonym: "हिन्दी" })).toBe("Hindi (हिन्दी)");
    expect(optionLabel({ name: "Esperanto", autonym: "esperanto" })).toBe("Esperanto");
    expect(tagLabel("ar")).toBe("Arabic (العربية)");
  });

  it("describes consent plainly, with nothing preselected before the user chooses", () => {
    expect(consentValue("not_asked")).toBe("");
    expect(consentValue("granted")).toBe("granted");
    expect(COMMUNITY_STATUS.declined).toBe("kept general");
    expect(FAITH_STATUS.not_asked).toBe("not chosen yet");
  });
});
