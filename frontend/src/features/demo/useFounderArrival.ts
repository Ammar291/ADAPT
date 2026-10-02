import { tr } from "@/i18n";
/**
 * Runs the "Founder Arrival" script, one act at a time, through the public services.
 *
 * Where each act stands is read back from the server (profile, documents, the plan,
 * research), so a reload mid-demo picks up where it left off (ARCHITECTURE.md D22). Only
 * the what-if outcome and which display-only acts were opened live in this page.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import type { UserDocument } from "@/domain/documents";
import { ASSUMPTION } from "@/domain/journey";
import type { RunStatus } from "@/domain/runs";
import type { DemoScenario, ScenarioDocument } from "@/domain/scenario";
import type { ScenarioOutcome, SimulationProgress } from "@/domain/simulate";
import { describeError } from "@/lib/api/errors";
import { useActiveJourney, useDocuments, useProfile, useResearchStatus } from "@/lib/api/hooks";
import { queryKeys } from "@/lib/api/queryKeys";
import { useServices } from "@/services/context";

export const SCENARIO_KEY = "founder-arrival";

export type ActKey = "profile" | "documents" | "plan" | "considerations" | "research" | "what_if" | "actions";
export const ACT_ORDER: ActKey[] = ["profile", "documents", "plan", "considerations", "research", "what_if", "actions"];
export type ActStatus = "locked" | "ready" | "running" | "done" | "failed";

/** Time each reading stage stays on screen before the next lights up (real events, paced). */
export const STAGE_PACE_MS = 650;
const FINISHED_RUN: RunStatus[] = ["awaiting_input", "succeeded", "failed", "cancelled"];

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function until<T>(what: string, probe: () => Promise<T>, done: (value: T) => boolean, timeoutMs: number, everyMs = 700): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await probe();
    if (done(value)) return value;
    if (Date.now() > deadline) throw new Error(`ADAPT is still working on ${what}. Try Continue again in a moment.`);
    await sleep(everyMs);
  }
}

/** The newest upload of a scenario document's kind. */
export function documentFor(documents: UserDocument[] | undefined, doc: ScenarioDocument): UserDocument | undefined {
  return [...(documents ?? [])].filter((d) => d.kind === doc.kind).sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0];
}

export function useFounderArrival() {
  const services = useServices();
  const scenarios = services.scenarios;
  const queryClient = useQueryClient();
  const scenario = useQuery({
    queryKey: ["scenario", SCENARIO_KEY],
    queryFn: ({ signal }) => scenarios!.get(SCENARIO_KEY, signal),
    enabled: scenarios !== null,
    staleTime: Infinity,
  });
  const profile = useProfile();
  const documents = useDocuments();
  const journey = useActiveJourney();
  const research = useResearchStatus();

  const [busy, setBusy] = useState<ActKey | null>(null);
  const [failed, setFailed] = useState<{ act: ActKey; message: string } | null>(null);
  const [opened, setOpened] = useState<Set<ActKey>>(new Set());
  const [planRunId, setPlanRunId] = useState<string | null>(null);
  const [whatIf, setWhatIf] = useState<ScenarioOutcome | null>(null);
  const [whatIfProgress, setWhatIfProgress] = useState<SimulationProgress | null>(null);
  const playing = useRef(false);
  const [isPlaying, setPlaying] = useState(false);

  const plan = journey.data && journey.data.nodes.length > 0 ? journey.data : null;
  const docs = useMemo(
    () => (scenario.data?.documents ?? []).map((doc) => ({ doc, upload: documentFor(documents.data, doc) })),
    [scenario.data, documents.data],
  );

  const done: Record<ActKey, boolean> = {
    profile: Boolean(profile.data),
    documents: docs.length > 0 && docs.every(({ doc, upload }) => upload && (doc.confirm ? upload.status === "confirmed" : upload.status === "extracted")),
    plan: plan !== null && busy !== "plan",
    considerations: plan !== null && opened.has("considerations"),
    research: research.data?.state === "ready" && research.data.itemCount > 0,
    what_if: whatIf !== null,
    actions: plan !== null && opened.has("actions"),
  };

  const statusOf = (act: ActKey): ActStatus => {
    if (busy === act) return "running";
    if (failed?.act === act) return "failed";
    if (done[act]) return "done";
    const index = ACT_ORDER.indexOf(act);
    const needs: ActKey[] = act === "considerations" || act === "research" || act === "actions" ? ["plan"] : act === "what_if" ? ["plan"] : ACT_ORDER.slice(0, index);
    return needs.every((k) => done[k]) ? "ready" : "locked";
  };

  // Runners read the latest server state through this ref (they outlive renders).
  const latest = useRef({ scenario: scenario.data, docs, plan });
  latest.current = { scenario: scenario.data, docs, plan };

  const invalidate = useCallback(
    (...keys: (readonly unknown[])[]) => Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey }))),
    [queryClient],
  );

  const runners: Record<ActKey, () => Promise<void>> = {
    profile: async () => {
      await scenarios!.saveProfile(SCENARIO_KEY);
      await invalidate(queryKeys.private.profile, queryKeys.me, queryKeys.private.userGraph);
    },
    documents: async () => {
      const s = latest.current.scenario as DemoScenario;
      for (const doc of s.documents) {
        let upload = documentFor(queryClient.getQueryData<UserDocument[]>(queryKeys.private.documents), doc);
        if (upload?.status === "confirmed") continue;
        const started = Date.now();
        if (!upload || upload.status === "failed") {
          const file = await scenarios!.documentFile(SCENARIO_KEY, doc.key);
          upload = await services.documents.upload(file, doc.kind);
          queryClient.setQueryData<UserDocument[]>(queryKeys.private.documents, (list) => [upload!, ...(list ?? [])]);
        }
        const id = upload.id;
        const read = await until(`the ${doc.title.toLowerCase()}`, () => services.documents.get(id), (d) => d.status !== "uploaded" && d.status !== "processing", 90_000);
        if (read.status === "failed") throw new Error(`ADAPT couldn't read the ${doc.title.toLowerCase()}.`);
        if (read.status === "needs_review") throw new Error(`ADAPT flagged details on the ${doc.title.toLowerCase()} for a check. Open it in Documents.`);
        await invalidate(queryKeys.private.documents, queryKeys.private.userGraph);
        // Let the four reading stages play at a readable pace before Kabir confirms.
        await sleep(Math.max(0, STAGE_PACE_MS * 4.5 - (Date.now() - started)));
        if (doc.confirm && read.status !== "confirmed") await services.documents.review(id, []);
        await invalidate(queryKeys.private.documents, queryKeys.private.document(id), queryKeys.private.userGraph);
        await sleep(500);
      }
    },
    plan: async () => {
      const ids = latest.current.docs.map(({ upload }) => upload?.id).filter((id): id is string => Boolean(id));
      const { runId } = await scenarios!.startJourney(SCENARIO_KEY, ids);
      setPlanRunId(runId);
      await invalidate(queryKeys.private.journeys, queryKeys.private.runs);
      const run = await until(tr("copy.the_plan_7c003df"), () => services.runs.get(runId), (r) => FINISHED_RUN.includes(r.status), 240_000, 900);
      if (run.status === "failed" || run.status === "cancelled") throw new Error(tr("copy.the_plan_run_stopped_open_agents_to_see_why_4accc71"));
      await invalidate(queryKeys.private.journeys, queryKeys.private.activeJourney, ["private", "journey"], queryKeys.private.approvalsAll, queryKeys.private.actions);
    },
    considerations: async () => {
      setOpened((s) => new Set(s).add("considerations"));
    },
    research: async () => {
      const current = latest.current.plan;
      if (!current) throw new Error(tr("copy.build_the_plan_first_f77cd90"));
      const { jobId } = await scenarios!.startResearch(SCENARIO_KEY, current.id);
      await invalidate(queryKeys.private.discover);
      await until(tr("copy.background_research_1634f77"), () => services.discover.status(), (s) => s.jobId === jobId && s.state !== "running", 180_000, 900);
      await invalidate(queryKeys.private.discover);
    },
    what_if: async () => {
      const current = latest.current.plan;
      if (!current) throw new Error(tr("copy.build_the_plan_first_f77cd90"));
      setWhatIfProgress(null);
      const outcome = await services.simulate.simulate(current.id, [{ key: ASSUMPTION.household, value: "alone" }], setWhatIfProgress);
      setWhatIf(outcome);
    },
    actions: async () => {
      await invalidate(queryKeys.private.actions, queryKeys.private.approvalsAll);
      setOpened((s) => new Set(s).add("actions"));
    },
  };

  const run = async (act: ActKey): Promise<boolean> => {
    setBusy(act);
    setFailed(null);
    try {
      await runners[act]();
      return true;
    } catch (error) {
      const described = describeError(error);
      setFailed({ act, message: described.detail ? `${described.title}. ${described.detail}` : described.title });
      return false;
    } finally {
      setBusy(null);
    }
  };

  const next = ACT_ORDER.find((act) => statusOf(act) === "ready" || statusOf(act) === "failed") ?? null;

  const playAll = async () => {
    if (playing.current) return;
    playing.current = true;
    setPlaying(true);
    try {
      for (const act of ACT_ORDER) {
        if (!playing.current) break;
        if (done[act] && act !== "considerations" && act !== "actions") continue;
        if (!(await run(act))) break;
        await sleep(1200);
      }
    } finally {
      playing.current = false;
      setPlaying(false);
    }
  };

  const stop = () => {
    playing.current = false;
  };

  const freshStart = async () => {
    stop();
    await scenarios?.freshStart();
    queryClient.clear();
    window.location.assign(window.location.pathname);
  };

  return {
    available: scenarios !== null,
    scenario,
    plan,
    planRunId,
    docs,
    research: research.data ?? null,
    whatIf,
    whatIfProgress,
    busy,
    failed,
    isPlaying,
    statusOf,
    next,
    run,
    playAll,
    stop,
    freshStart,
  };
}

export type FounderArrival = ReturnType<typeof useFounderArrival>;
