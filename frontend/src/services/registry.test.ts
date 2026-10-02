import { describe, expect, it } from "vitest";
import { resolveSources } from "./registry";
import type { SystemInfo } from "./types";

function info(features: Partial<SystemInfo["features"]> = {}): SystemInfo {
  return {
    appName: "ADAPT",
    version: "1",
    environment: "test",
    demoMode: true,
    adapters: [],
    features: {
      journeys: false,
      documentUpload: false,
      voice: false,
      webResearch: false,
      demoAuth: true,
      onboarding: false,
      discover: false,
      appointments: false,
      approvals: false,
      generatedDocuments: false,
      ...features,
    },
  };
}

describe("resolveSources", () => {
  it("uses mocks for everything in mock mode", () => {
    expect(Object.values(resolveSources("mock", null)).every((s) => s === "mock")).toBe(true);
  });

  it("uses the API where it ships and mocks elsewhere in auto mode", () => {
    const sources = resolveSources("auto", info({ documentUpload: true, webResearch: true }));
    expect(sources.session).toBe("live");
    expect(sources.graphs).toBe("live");
    expect(sources.documents).toBe("live");
    expect(sources.discover).toBe("live");
    expect(sources.journeys).toBe("mock");
    // The assistant can't see a mocked plan, so it stays with the mock too.
    expect(sources.assistant).toBe("mock");
    expect(sources.voice).toBe("unavailable");
  });

  it("never mocks in live mode", () => {
    const sources = resolveSources("live", info());
    expect(sources.journeys).toBe("unavailable");
    expect(sources.documents).toBe("unavailable");
    expect(Object.values(sources)).not.toContain("mock");
  });
});
