/**
 * Chooses, per capability, where data comes from:
 *   live        — the backend ships the endpoint (feature flag on) and a live adapter exists
 *   mock        — `auto`/`mock` data mode and the capability isn't live
 *   unavailable — `live` data mode and the capability isn't live; the UI gates it
 */
import type { DataMode } from "@/lib/config";
import { createLiveActivity } from "./live/activity";
import { liveGraphs, liveRuns, liveSession } from "./live/foundation";
import { liveDocuments } from "./live/documents";
import { liveGenerated } from "./live/generated";
import { liveApprovals, liveJourneyRuns, liveJourneys, liveSimulate } from "./live/journeys";
import { liveProfile } from "./live/profile";
import { createLiveDiscoverService } from "./live/research";
import { liveScenarios, type ScenarioService } from "./live/scenarios";
import { liveUserGraph } from "./live/userGraph";
import type { Capability, RunService, Services, Source, SystemInfo } from "./types";
import { CapabilityUnavailableError } from "./types";

/**
 * The mock layer, loaded with a dynamic import only in `auto` and `mock` data modes, so
 * `live` builds never download it (it carries the governance snapshot and the mock planner).
 */
export type MockModule = typeof import("./mock");

/**
 * Capabilities with a live adapter. Owners of new endpoints add theirs here (see
 * ARCHITECTURE.md, "Frontend data layer").
 */
const LIVE_ADAPTERS = new Set<Capability>(["session", "graphs", "runs", "discover", "documents", "profile", "journeys", "approvals", "simulate", "generated"]);

type Feature = keyof SystemInfo["features"];

const FEATURE_FOR: Partial<Record<Capability, Feature>> = {
  profile: "onboarding",
  journeys: "journeys",
  generated: "generatedDocuments",
  approvals: "approvals",
  simulate: "journeys",
  documents: "documentUpload",
  discover: "webResearch",
  voice: "voice",
};

function unavailable<T extends object>(capability: Capability): T {
  return new Proxy({} as T, {
    get(_target, prop) {
      if (prop === "then") return undefined;
      return () => Promise.reject(new CapabilityUnavailableError(capability));
    },
  });
}

export function resolveSources(mode: DataMode, info: SystemInfo | null): Record<Capability, Source> {
  const all: Capability[] = ["session", "graphs", "runs", "profile", "journeys", "documents", "generated", "approvals", "discover", "simulate", "assistant", "voice"];
  const sources = {} as Record<Capability, Source>;
  for (const capability of all) {
    if (mode === "mock") {
      sources[capability] = "mock";
      continue;
    }
    const feature = FEATURE_FOR[capability];
    const shipped = feature ? info?.features[feature] === true : true;
    const live = shipped && LIVE_ADAPTERS.has(capability);
    sources[capability] = live ? "live" : mode === "auto" ? "mock" : "unavailable";
  }
  // The assistant (features/voice) talks to the backend. While journeys are mocked in the
  // frontend, the backend assistant can't see the plan the UI shows, so it stays mock too.
  if (mode !== "mock") sources.assistant = sources.journeys === "live" ? "live" : mode === "auto" ? "mock" : "live";
  // Live voice is owned by features/voice and gated by the backend's `voice` flag.
  if (mode !== "mock") sources.voice = info?.features.voice ? "live" : "unavailable";
  return sources;
}

/** Runs from the mock engine and the live API side by side, routed by who owns the id. */
function composeRuns(journeysSource: Source, mock: MockModule | null): RunService {
  if (journeysSource === "live" || !mock) {
    return {
      ...unavailable<RunService>("runs"),
      ...liveRuns,
      ...(journeysSource === "live" ? liveJourneyRuns : {}),
    } as RunService;
  }
  const { mockRuns, getMockRun } = mock;
  return {
    workflow: mockRuns.workflow,
    get: (id, signal) => (getMockRun(id) ? mockRuns.get(id, signal) : liveRuns.get(id, signal)),
    recent: async (signal) => {
      const [mock, live] = await Promise.all([mockRuns.recent(signal), liveRuns.recent(signal).catch(() => [])]);
      return [...mock, ...live].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    },
    subscribe: (id, sub) => (getMockRun(id) ? mockRuns.subscribe(id, sub) : liveRuns.subscribe(id, sub)),
    answer: mockRuns.answer,
    review: (id, signal) => (getMockRun(id) ? mockRuns.review(id, signal) : liveRuns.review(id, signal)),
    resume: mockRuns.resume,
    cancel: (id) => (getMockRun(id) ? mockRuns.cancel(id) : liveRuns.cancel(id)),
    startDiagnostic: liveRuns.startDiagnostic,
  };
}

export function createServices(
  mode: DataMode,
  info: SystemInfo | null,
  mock: MockModule | null,
): Services & { demo: MockModule["mockDemo"] | null; scenarios: ScenarioService | null } {
  const sources = resolveSources(mode, info);
  if (!mock) {
    // Without the mock layer nothing can be mocked: those capabilities are unavailable.
    for (const key of Object.keys(sources) as Capability[]) if (sources[key] === "mock") sources[key] = "unavailable";
  }
  const pick = <T extends object>(capability: Capability, live: T | null, mocked: T | undefined): T =>
    sources[capability] === "live" && live ? live : sources[capability] === "mock" && mocked ? mocked : unavailable<T>(capability);

  const session = pick("session", liveSession, mock?.mockSession);
  const mockDemo = mock?.mockDemo ?? null;
  const graphs =
    sources.graphs === "mock" && mock
      ? mock.mockGraphs
      : {
          governance: liveGraphs.governance,
          governanceNode: liveGraphs.governanceNode,
          // Until the journey pipeline fills the live twin, it comes from the same mock
          // state as the journey, so the two agree.
          user: sources.journeys === "live" || sources.documents === "live" || !mock ? liveUserGraph.user : mock.mockGraphs.user,
        };
  const runs = mode === "mock" && mock ? mock.mockRuns : composeRuns(sources.journeys, mock);

  // Server state changes reach the UI as invalidation topics: from the mock store for mocked
  // capabilities, and from the backend's agent event log for live ones.
  const liveData = (["journeys", "documents", "discover", "approvals"] as const).some((c) => sources[c] === "live");
  const activity = liveData ? createLiveActivity() : null;
  const feeds = [mock ? (l: (topics: string[]) => void) => mock.store.subscribe(l) : null, activity ? activity.subscribe : null].filter(
    (feed): feed is (listener: (topics: string[]) => void) => () => void => feed !== null,
  );
  const onChange = feeds.length
    ? (listener: (topics: string[]) => void) => {
        const stops = feeds.map((feed) => feed(listener));
        return () => stops.forEach((stop) => stop());
      }
    : undefined;
  /** Starting something server-side: look for its events now rather than at the next tick. */
  const poking = <T extends object>(service: T, method: keyof T): T => {
    if (!activity) return service;
    return new Proxy(service, {
      get(target, prop, receiver) {
        const value = Reflect.get(target, prop, receiver) as unknown;
        if (prop !== method || typeof value !== "function") return value;
        return (...args: unknown[]) => Promise.resolve(value.apply(target, args)).finally(() => activity.poke());
      },
    });
  };

  const journeys = pick("journeys", liveJourneys, mock?.mockJourneys);
  const documents = pick("documents", liveDocuments, mock?.mockDocuments);
  const discover = pick("discover", sources.discover === "live" ? createLiveDiscoverService() : null, mock?.mockDiscover);

  const services = {
    sources,
    onChange,
    session:
      sources.session === "live" && mode === "auto" && mockDemo
        ? {
            ...session,
            // Mock research needs to see live consent choices.
            me: async (signal?: AbortSignal) => {
              const user = await session.me(signal);
              mockDemo.syncPreferences(user.preferences);
              return user;
            },
            updatePreferences: async (update: Parameters<typeof session.updatePreferences>[0]) => {
              const user = await session.updatePreferences(update);
              mockDemo.syncPreferences(user.preferences);
              return user;
            },
          }
        : session,
    profile: pick("profile", liveProfile, mock?.mockProfile),
    graphs,
    runs,
    journeys: poking(journeys, "start"),
    documents: poking(documents, "upload"),
    generated: pick("generated", liveGenerated, mock?.mockGenerated),
    approvals: pick("approvals", liveApprovals, mock?.mockApprovals),
    discover: poking(discover, "start"),
    simulate: pick("simulate", liveSimulate, mock?.mockSimulate),
    // Typed turns in mock mode; live conversations go through features/voice.
    assistant: mock?.mockAssistant ?? unavailable<Services["assistant"]>("assistant"),
    demo: sources.journeys === "mock" ? mockDemo : null,
    // Scripted demo runs drive the real pipeline, so they need it live end to end.
    scenarios:
      info?.features.demoScenarios && (["journeys", "documents", "discover", "simulate", "approvals"] as const).every((c) => sources[c] === "live")
        ? liveScenarios
        : null,
  };
  return services;
}

export type AppServices = ReturnType<typeof createServices>;
