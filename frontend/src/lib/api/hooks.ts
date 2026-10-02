import { tr } from "@/i18n";
/**
 * Server-state hooks (TanStack Query) over the service layer. Feature code uses these and
 * never calls services or `fetch` directly. Server state stays in memory only.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import type { DiscoverSection } from "@/domain/discover";
import type { DocumentKind, FieldCorrection, ReviewAnswer } from "@/domain/documents";
import type { Journey } from "@/domain/journey";
import type { MoveProfile, PreferencesUpdate } from "@/domain/profile";
import type { RunKind } from "@/domain/runs";
import type { AssumptionChange, ScenarioOutcome, SimulationProgress } from "@/domain/simulate";
import { useServices } from "@/services/context";
import type { StartJourneyInput } from "@/services/types";
import { ApiError } from "./errors";
import { queryKeys } from "./queryKeys";

// --- session and system ---------------------------------------------------------------------

export function useSystemInfo() {
  const { session } = useServices();
  return useQuery({ queryKey: queryKeys.system, queryFn: ({ signal }) => session.systemInfo(signal), staleTime: 5 * 60_000 });
}

export function useSession() {
  const { session } = useServices();
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: ({ signal }) => session.me(signal),
    staleTime: 10 * 60_000,
    retry: (count, error) => error instanceof ApiError && error.isRetryable && count < 3,
  });
}

export function useUpdatePreferences() {
  const { session } = useServices();
  const client = useQueryClient();
  return useMutation({
    scope: { id: "profile-preferences" },
    mutationFn: (update: PreferencesUpdate) => session.updatePreferences(update),
    onSuccess: (user) => {
      client.setQueryData(queryKeys.me, user);
      void client.invalidateQueries({ queryKey: queryKeys.private.discover });
    },
  });
}

export function useSignOut() {
  const { session } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => session.signOut(),
    onSuccess: async () => {
      await Promise.all([
        client.cancelQueries({ queryKey: queryKeys.private.all }),
        client.cancelQueries({ queryKey: queryKeys.me }),
      ]);
      const { voice } = await import("@/features/voice/controller");
      voice.newConversation();
      client.removeQueries({ queryKey: queryKeys.private.all });
      client.removeQueries({ queryKey: queryKeys.me });
    },
  });
}

// --- profile and journeys ----------------------------------------------------------------------

export function useProfile() {
  const { profile } = useServices();
  return useQuery({ queryKey: queryKeys.private.profile, queryFn: ({ signal }) => profile.get(signal) });
}

export function useSaveProfile() {
  const { profile } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (value: MoveProfile) => profile.save(value),
    onSuccess: (value) => client.setQueryData(queryKeys.private.profile, value),
  });
}

export function useJourneys() {
  const { journeys } = useServices();
  return useQuery({ queryKey: queryKeys.private.journeys, queryFn: ({ signal }) => journeys.list(signal) });
}

/** The user's current plan, or null when they don't have one yet. */
export function useActiveJourney() {
  const { journeys } = useServices();
  return useQuery({
    queryKey: queryKeys.private.activeJourney,
    queryFn: async ({ signal }): Promise<Journey | null> => {
      const list = await journeys.list(signal);
      const active = list.find((j) => j.status === "active") ?? list.find((j) => j.status === "draft");
      return active ? journeys.get(active.id, signal) : null;
    },
  });
}

export function useJourney(id: string | null) {
  const { journeys } = useServices();
  return useQuery({
    queryKey: queryKeys.private.journey(id ?? ""),
    queryFn: ({ signal }) => journeys.get(id!, signal),
    enabled: Boolean(id),
  });
}

export function useStartJourney() {
  const { journeys } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: StartJourneyInput) => journeys.start(input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.private.all });
    },
  });
}

function useJourneyUpdate<A extends unknown[]>(fn: (...args: A) => Promise<Journey>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: A) => fn(...args),
    onSuccess: (journey) => {
      client.setQueryData(queryKeys.private.journey(journey.id), journey);
      client.setQueryData(queryKeys.private.activeJourney, journey);
      void client.invalidateQueries({ queryKey: queryKeys.private.journeys });
    },
  });
}

export function useMarkNodeDone() {
  const { journeys } = useServices();
  return useJourneyUpdate((journeyId: string, nodeKey: string) => journeys.markDone(journeyId, nodeKey));
}

export function useAnswerNode() {
  const { journeys } = useServices();
  return useJourneyUpdate((journeyId: string, nodeKey: string, answer: string) => journeys.answerNode(journeyId, nodeKey, answer));
}

/** Demo only: load a sample plan. Null when journeys come from the real API. */
export function useDemo() {
  const services = useServices();
  const client = useQueryClient();
  const seed = useMutation({
    mutationFn: () => services.demo!.seedSample(),
    onSuccess: () => void client.invalidateQueries(),
  });
  return services.demo ? { seedSample: seed } : null;
}

// --- runs ----------------------------------------------------------------------------------------

export function useWorkflow(kind: RunKind) {
  const { runs } = useServices();
  return useQuery({ queryKey: queryKeys.workflow(kind), queryFn: ({ signal }) => runs.workflow(kind, signal), staleTime: Infinity });
}

export function useRecentRuns() {
  const { runs } = useServices();
  return useQuery({ queryKey: queryKeys.private.runs, queryFn: ({ signal }) => runs.recent(signal), refetchInterval: 5_000 });
}

export function useRun(runId: string | null) {
  const { runs } = useServices();
  return useQuery({ queryKey: queryKeys.private.run(runId ?? ""), queryFn: ({ signal }) => runs.get(runId!, signal), enabled: Boolean(runId) });
}

export function useRunReview(runId: string | null, enabled = true) {
  const { runs } = useServices();
  return useQuery({
    queryKey: queryKeys.private.review(runId ?? ""),
    queryFn: ({ signal }) => runs.review(runId!, signal),
    enabled: Boolean(runId) && enabled,
  });
}

export function useResumeRun() {
  const { runs } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, reviewId, answer }: { runId: string; reviewId: string; answer: ReviewAnswer }) => runs.resume(runId, reviewId, answer),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.private.all }),
  });
}

export function useCancelRun() {
  const { runs } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => runs.cancel(runId),
    onSuccess: () => {
      // Its open approvals expired and the actions went back to draft.
      void client.invalidateQueries({ queryKey: queryKeys.private.runs });
      void client.invalidateQueries({ queryKey: queryKeys.private.approvalsAll });
      void client.invalidateQueries({ queryKey: queryKeys.private.actions });
      void client.invalidateQueries({ queryKey: ["private", "journey"] });
    },
  });
}

export function useStartDiagnosticRun() {
  const { runs } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => runs.startDiagnostic(),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.private.runs }),
  });
}

// --- knowledge graphs ------------------------------------------------------------------------

export function useGovernanceGraph(types?: string[], q?: string) {
  const { graphs } = useServices();
  return useQuery({
    queryKey: queryKeys.governance.graph(types, q),
    queryFn: ({ signal }) => graphs.governance({ types, q }, signal),
    staleTime: 10 * 60_000,
  });
}

export function useGovernanceNode(ref: string | null) {
  const { graphs } = useServices();
  return useQuery({
    queryKey: queryKeys.governance.node(ref ?? ""),
    queryFn: ({ signal }) => graphs.governanceNode(ref!, signal),
    enabled: Boolean(ref),
    staleTime: 10 * 60_000,
  });
}

export function useUserGraph() {
  const { graphs } = useServices();
  return useQuery({ queryKey: queryKeys.private.userGraph, queryFn: ({ signal }) => graphs.user(signal) });
}

// --- documents ---------------------------------------------------------------------------------

export function useDocuments() {
  const { documents } = useServices();
  return useQuery({
    queryKey: queryKeys.private.documents,
    queryFn: ({ signal }) => documents.list(signal),
    // Poll while anything is being processed (live mode has no push yet).
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === "uploaded" || d.status === "processing") ? 2_500 : false),
  });
}

export function useUploadDocument() {
  const { documents } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, kind }: { file: File; kind: DocumentKind }) => documents.upload(file, kind),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.private.documents }),
  });
}

export function useReviewDocument() {
  const { documents } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, corrections }: { id: string; corrections: FieldCorrection[] }) => documents.review(id, corrections),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.private.documents });
      void client.invalidateQueries({ queryKey: ["private", "journey"] });
    },
  });
}

export function useDeleteDocument() {
  const { documents } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => documents.remove(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.private.documents }),
  });
}

export function useGeneratedDocuments() {
  const { generated } = useServices();
  return useQuery({ queryKey: queryKeys.private.generated, queryFn: ({ signal }) => generated.list(signal) });
}

export function useGeneratedDocumentActions() {
  const { generated } = useServices();
  const client = useQueryClient();
  const onSuccess = () => void client.invalidateQueries({ queryKey: queryKeys.private.generated });
  return {
    approve: useMutation({ mutationFn: (id: string) => generated.approve(id), onSuccess }),
    discard: useMutation({ mutationFn: (id: string) => generated.discard(id), onSuccess }),
    update: useMutation({ mutationFn: ({ id, body }: { id: string; body: string }) => generated.update(id, body), onSuccess }),
  };
}

// --- approvals and actions ---------------------------------------------------------------------

export function useApprovals(status?: "pending" | "approved" | "rejected") {
  const { approvals } = useServices();
  return useQuery({ queryKey: queryKeys.private.approvals(status), queryFn: ({ signal }) => approvals.list(status, signal) });
}

export function useDecideApproval() {
  const { approvals } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision, note }: { id: string; decision: "approve" | "reject"; note?: string }) => approvals.decide(id, decision, note),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.private.approvalsAll });
      void client.invalidateQueries({ queryKey: queryKeys.private.actions });
      void client.invalidateQueries({ queryKey: ["private", "journey"] });
      void client.invalidateQueries({ queryKey: queryKeys.private.runs });
    },
  });
}

export function usePrepareAction() {
  const { approvals } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (journeyNodeKey: string) => approvals.prepare(journeyNodeKey),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.private.approvalsAll });
      void client.invalidateQueries({ queryKey: ["private", "journey"] });
    },
  });
}

export function useActions() {
  const { approvals } = useServices();
  return useQuery({ queryKey: queryKeys.private.actions, queryFn: ({ signal }) => approvals.actions(signal) });
}

// --- discover ----------------------------------------------------------------------------------

export function useDiscoverItems() {
  const { discover } = useServices();
  return useQuery({ queryKey: queryKeys.private.discoverItems, queryFn: ({ signal }) => discover.items(signal) });
}

export function useResearchStatus(enabled = true) {
  const { discover } = useServices();
  return useQuery({
    queryKey: queryKeys.private.discoverStatus,
    queryFn: ({ signal }) => discover.status(signal),
    enabled,
    refetchInterval: (query) => (query.state.data?.state === "running" ? 4_000 : false),
  });
}

export function useDiscoverActions() {
  const { discover } = useServices();
  const client = useQueryClient();
  const onSuccess = () => void client.invalidateQueries({ queryKey: queryKeys.private.discover });
  return {
    start: useMutation({ mutationFn: (sections?: DiscoverSection[]) => discover.start({ categories: sections }), onSuccess }),
    save: useMutation({ mutationFn: ({ id, saved }: { id: string; saved: boolean }) => discover.save(id, saved), onSuccess }),
    addToJourney: useMutation({
      mutationFn: (id: string) => discover.addToJourney(id),
      onSuccess: () => {
        onSuccess();
        void client.invalidateQueries({ queryKey: ["private", "journey"] });
      },
    }),
    markSeen: useMutation({ mutationFn: (jobId: string) => discover.markSeen(jobId), onSuccess }),
  };
}

// --- simulate ---------------------------------------------------------------------------------------

/** The assumptions a what-if can change for this plan (assumption keys). */
export function useSimulationVariables(journeyId: string) {
  const { simulate } = useServices();
  return useQuery({
    queryKey: ["private", "journey", journeyId, "what-if-variables"],
    queryFn: ({ signal }) => simulate.variables(journeyId, signal),
    staleTime: 5 * 60_000,
  });
}

/** Runs a what-if and exposes streaming progress while it runs. */
export function useSimulation() {
  const { simulate } = useServices();
  const [progress, setProgress] = useState<SimulationProgress | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: ({ journeyId, changes }: { journeyId: string; changes: AssumptionChange[] }): Promise<ScenarioOutcome> => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setProgress({ stage: "queued", label: tr("copy.starting_7725e05"), progress: 0 });
      return simulate.simulate(journeyId, changes, setProgress, controller.signal);
    },
  });
  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setProgress(null);
    mutation.reset();
  }, [mutation]);
  return { ...mutation, progress, cancel };
}
