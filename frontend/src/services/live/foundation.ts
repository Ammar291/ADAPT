/**
 * Live adapters for the endpoints the backend ships today: session and preferences, system
 * info, the governance graph, the agent topology and runs (list, status, SSE, cancel).
 * This is the only place that knows those wire formats.
 */
import type { Preferences, User } from "@/domain/profile";
import type { AgentWorkflow, RunSummary } from "@/domain/runs";
import { requestedSeed } from "@/app/demoSeed";
import { currentLocale } from "@/i18n";
import { api, buildUrl } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { GraphService, RunRef, RunService, SessionService, SystemInfo } from "../types";
import { CapabilityUnavailableError } from "../types";
import { normaliseRunEvent } from "./events";
import { toGovernanceEdge, toGovernanceGraph, toGovernanceNode } from "./governanceFormat";
import { paths } from "./paths";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

// --- session ------------------------------------------------------------------------------------

function toPreferences(raw: Raw): Preferences {
  return {
    preferredLanguage: raw.preferred_language ?? "en",
    uiLocale: raw.ui_locale ?? "en",
    faithPersonalization: raw.faith_personalization ?? "not_asked",
    communityPersonalization: raw.community_personalization ?? "not_asked",
    voiceTranscriptsRetained: raw.voice_transcripts_retained ?? false,
  };
}

function toUser(raw: Raw): User {
  return {
    id: raw.id,
    displayName: raw.display_name ?? null,
    isDemo: raw.is_demo ?? false,
    preferences: toPreferences(raw.preferences ?? {}),
    createdAt: raw.created_at,
  };
}

export const liveSession: SessionService = {
  async me(signal) {
    try {
      return toUser(await api.get<Raw>(paths.me, { signal }));
    } catch (error) {
      // No session yet: where demo sign-in is enabled, start a private demo session.
      if (error instanceof ApiError && error.isUnauthorized) {
        // `?seed=sample` signs into the backend's seeded fictional household (demos).
        const session = await api.post<Raw>(paths.demoSession, { ui_locale: currentLocale(), ...(requestedSeed === "sample" ? { sample_household: true } : {}) });
        return toUser(session.user);
      }
      throw error;
    }
  },
  async updatePreferences(update) {
    const body: Raw = {};
    if (update.preferredLanguage !== undefined) body.preferred_language = update.preferredLanguage;
    if (update.uiLocale !== undefined) body.ui_locale = update.uiLocale;
    if (update.faithPersonalization !== undefined) body.faith_personalization = update.faithPersonalization;
    if (update.communityPersonalization !== undefined) body.community_personalization = update.communityPersonalization;
    if (update.voiceTranscriptsRetained !== undefined) body.voice_transcripts_retained = update.voiceTranscriptsRetained;
    return toUser(await api.patch<Raw>(paths.preferences, body));
  },
  async signOut() {
    await api.post<void>(paths.logout);
  },
  async systemInfo(signal) {
    const raw = await api.get<Raw>(paths.systemInfo, { signal });
    const f = raw.features ?? {};
    const info: SystemInfo = {
      appName: raw.app_name,
      version: raw.version,
      environment: raw.environment,
      demoMode: raw.demo_mode,
      adapters: raw.adapters ?? [],
      features: {
        journeys: f.journeys === true,
        documentUpload: f.document_upload === true,
        voice: f.voice === true,
        webResearch: f.web_research === true,
        demoAuth: f.demo_auth === true,
        onboarding: f.onboarding === true,
        discover: f.discover === true,
        appointments: f.appointments === true,
        approvals: f.approvals === true,
        generatedDocuments: f.generated_documents === true,
        demoScenarios: f.demo_scenarios === true,
      },
    };
    return info;
  },
};

// --- graphs -------------------------------------------------------------------------------------

/** The public governance graph. The private user graph is `liveUserGraph` (./userGraph). */
export const liveGraphs: Pick<GraphService, "governance" | "governanceNode"> = {
  async governance(params = {}, signal) {
    return toGovernanceGraph(await api.get<Raw>(paths.governanceGraph, { query: { type: params.types, q: params.q }, signal }));
  },
  async governanceNode(ref, signal) {
    const raw = await api.get<Raw>(paths.governanceNode(ref), { signal });
    const passages = new Map<string, Raw>(((raw.evidence ?? []) as Raw[]).map((p) => [p.id, p]));
    return {
      node: toGovernanceNode(raw.node, passages),
      neighbours: (raw.neighbours ?? []).map((n: Raw) => toGovernanceNode(n, passages)),
      edges: (raw.edges ?? []).map(toGovernanceEdge),
    };
  },
};

// --- runs ---------------------------------------------------------------------------------------

export function toRun(raw: Raw): RunSummary {
  return {
    id: raw.id,
    kind: raw.kind,
    status: raw.status,
    journeyId: raw.journey_id ?? null,
    lastSeq: raw.last_event_seq ?? raw.last_seq ?? 0,
    createdAt: raw.created_at,
    startedAt: raw.started_at ?? null,
    finishedAt: raw.finished_at ?? null,
  };
}

function toWorkflow(raw: Raw): AgentWorkflow {
  return {
    id: raw.graph ?? raw.id ?? "journey",
    version: String(raw.version ?? "1"),
    stages: (raw.nodes ?? raw.stages ?? []).map((n: Raw) => ({
      id: n.id,
      label: n.label,
      description: n.description ?? "",
      kind: n.kind === "router" ? "tool" : n.kind,
      lane: n.lane ?? 0,
    })),
    edges: (raw.edges ?? [])
      .filter((e: Raw) => !String(e.source).startsWith("__") && !String(e.target).startsWith("__"))
      .map((e: Raw) => ({ source: e.source, target: e.target, condition: e.condition ?? null })),
  };
}

export const liveRuns: Pick<RunService, "workflow" | "get" | "recent" | "subscribe" | "startDiagnostic" | "cancel" | "answer" | "review" | "resume"> = {
  async workflow(kind, signal) {
    // Journey and what-if graphs publish their topology. Other agents (e.g. the system check)
    // don't: the console then draws the stages from the run's own events.
    if (kind !== "journey" && kind !== "what_if") return { id: kind, version: "1", stages: [], edges: [] };
    return toWorkflow(await api.get<Raw>(paths.topology(kind), { signal }));
  },
  async get(runId, signal) {
    return toRun(await api.get<Raw>(paths.run(runId), { signal }));
  },
  async recent(signal) {
    // The server's list, so runs started on another device (or by voice, or by the journey
    // agent itself, like research) show up too, and survive a reload.
    return (await api.get<Raw[]>(paths.runs, { query: { limit: 20 }, signal })).map(toRun);
  },
  subscribe(runId, { onEvent, onState }) {
    onState("connecting");
    const source = new EventSource(buildUrl(paths.runEvents(runId)), { withCredentials: true });
    source.onopen = () => onState("open");
    source.onmessage = (message: MessageEvent<string>) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(message.data);
      } catch {
        return; // the durable log is the source of truth; skip malformed frames
      }
      const event = normaliseRunEvent(parsed);
      if (!event) return;
      onEvent(event);
      if (event.event === "run_completed" || event.event === "run_failed" || event.event === "run_cancelled") {
        source.close();
        onState("closed");
      }
    };
    source.onerror = () => {
      // CONNECTING: the browser retries with Last-Event-ID. CLOSED: it gave up.
      onState(source.readyState === EventSource.CLOSED ? "closed" : "reconnecting");
    };
    return () => source.close();
  },
  async startDiagnostic(): Promise<RunRef> {
    const started = await api.post<Raw>(paths.startRun, { agent: "diagnostic", input: {} });
    const run = toRun(started.run);
    return { runId: run.id, kind: run.kind, journeyId: run.journeyId };
  },
  /** Only a run that is waiting for the person can be cancelled (409 `run_not_cancellable`). */
  async cancel(runId) {
    return toRun(await api.post<Raw>(paths.cancelRun(runId)));
  },
  async answer() {
    throw new CapabilityUnavailableError("runs");
  },
  async review() {
    return null;
  },
  async resume() {
    throw new CapabilityUnavailableError("runs");
  },
};
