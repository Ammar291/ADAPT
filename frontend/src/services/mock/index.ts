/**
 * Typed in-memory implementations of every service interface. Used for capabilities whose
 * API hasn't shipped (auto mode) or for everything (mock mode).
 */
import { ASSUMPTION, type JourneySummary } from "@/domain/journey";
import type { ReviewAnswer } from "@/domain/documents";
import type { AssumptionChange } from "@/domain/simulate";
import { ApiError } from "@/lib/api/errors";
import { completion } from "@/lib/journey/analysis";
import { diffJourneys } from "@/lib/journey/diff";
import type {
  ApprovalService,
  DiscoverService,
  DocumentService,
  GeneratedDocumentService,
  GraphService,
  JourneyService,
  ProfileService,
  RunService,
  SessionService,
  SimulationService,
  AssistantService,
} from "../types";
import { mockRespond } from "./assistant";
import { specimenExtraction } from "./content";
import { governanceDetail, governanceGraph } from "./governance";
import { startJourneyRun, wireApprovalsToRuns } from "./journeyRun";
import { buildJourney, profileFromAssumptions } from "./planner";
import { cancelRun, getRun, recentRuns, resumeRun, reviewOf, startRun, subscribeRun } from "./runEngine";

/** Whether a run belongs to the mock engine (runs from both sources coexist in auto mode). */
export const getMockRun = getRun;
import { sampleProfile, store } from "./store";
import { clone, delay, latency, uid } from "./util";
import { DIAGNOSTIC_WORKFLOW, WHAT_IF_WORKFLOW, workflowFor } from "./workflows";

const notFound = (what: string) => new ApiError({ title: `${what} not found`, status: 404, code: "not_found" });

wireApprovalsToRuns((runId) => resumeRun(runId));

export { store };

export const mockSession: SessionService = {
  async me(signal) {
    await latency(signal, 0.5);
    return clone(store.user);
  },
  async updatePreferences(update) {
    await latency();
    const before = store.user.preferences.faithPersonalization;
    store.user.preferences = { ...store.user.preferences, ...update };
    if (update.faithPersonalization && update.faithPersonalization !== before && store.research.state === "ready") {
      void store.startResearch();
    }
    store.emit("session", "discover");
    return clone(store.user);
  },
  async signOut() {
    await latency();
    store.reset();
  },
  async systemInfo(signal) {
    await latency(signal, 0.3);
    return {
      appName: "ADAPT",
      version: "0.1.0",
      environment: "mock",
      demoMode: true,
      adapters: ["llm", "embeddings", "ocr", "voice", "web_search", "actions"].map((capability) => ({ capability, mode: "demo" as const, provider: "frontend-mock" })),
      features: {
        journeys: true,
        documentUpload: true,
        voice: false,
        webResearch: true,
        demoAuth: true,
        onboarding: true,
        discover: true,
        appointments: true,
        approvals: true,
        generatedDocuments: true,
      },
    };
  },
};

export const mockProfile: ProfileService = {
  async get(signal) {
    await latency(signal, 0.5);
    return store.profile ? clone(store.profile) : null;
  },
  async save(profile) {
    await latency();
    store.profile = clone(profile);
    store.emit("profile", "journeys", "graph");
    return clone(profile);
  },
};

export const mockGraphs: GraphService = {
  async governance(params = {}, signal) {
    await latency(signal);
    return clone(governanceGraph(params));
  },
  async governanceNode(ref, signal) {
    await latency(signal, 0.6);
    const detail = governanceDetail(ref);
    if (!detail) throw notFound("Service");
    return clone(detail);
  },
  async user(signal) {
    await latency(signal);
    return clone(store.userGraph());
  },
};

export const mockRuns: RunService = {
  async workflow(kind, signal) {
    await latency(signal, 0.3);
    return clone(workflowFor(kind));
  },
  async get(runId, signal) {
    await latency(signal, 0.3);
    const run = getRun(runId);
    if (!run) throw notFound("Run");
    return run;
  },
  async recent(signal) {
    await latency(signal, 0.3);
    return recentRuns();
  },
  subscribe: subscribeRun,
  async answer(runId) {
    await latency();
    resumeRun(runId);
    const run = getRun(runId)!;
    return { runId, kind: run.kind, journeyId: run.journeyId };
  },
  async review(runId, signal) {
    await latency(signal, 0.4);
    const review = reviewOf(runId);
    if (!review) return null;
    if (review.gate === "action_approval") {
      return { ...review, items: review.items.map((a) => clone(store.approvals.get(a.id) ?? a)) };
    }
    return clone(review);
  },
  async resume(runId, _reviewId, answer: ReviewAnswer) {
    await latency();
    if (answer.gate === "document_correction") {
      for (const doc of answer.documents) {
        const stored = store.documents.get(doc.documentId);
        if (stored && doc.confirm) stored.status = "confirmed";
      }
      store.emit("documents", "journeys");
    }
    resumeRun(runId);
    const run = getRun(runId)!;
    return { runId, kind: run.kind, journeyId: run.journeyId };
  },
  async cancel(runId) {
    await latency(undefined, 0.5);
    const run = cancelRun(runId);
    if (!run) throw notFound("Run");
    store.emit("runs");
    return run;
  },
  async startDiagnostic() {
    await latency();
    const runId = startRun("diagnostic", async (ctx) => {
      for (const stage of DIAGNOSTIC_WORKFLOW.stages) {
        await ctx.stage(stage.id, stage.label, async () => {
          ctx.emit({ event: "node_progress", node: stage.id, message: stage.description, progress: 0.5 });
          await ctx.wait(700);
          return "OK";
        });
      }
      return { summary: "Every part of the pipeline responded." };
    });
    store.emit("runs");
    return { runId, kind: "diagnostic", journeyId: null };
  },
};

function summaryOf(): JourneySummary[] {
  const journey = store.journey();
  if (!journey) return [];
  const { done, total } = completion(journey);
  return [{ id: journey.id, title: journey.title, status: journey.status, nodeCount: total, completedCount: done, updatedAt: journey.updatedAt }];
}

export const mockJourneys: JourneyService = {
  async list(signal) {
    await latency(signal, 0.6);
    return summaryOf();
  },
  async get(id, signal) {
    await latency(signal);
    const journey = id === store.journeyId ? store.journey() : store.scenarios.get(id);
    if (!journey) throw notFound("Journey");
    return clone(journey);
  },
  async start(input) {
    await latency();
    const preferences = store.user.preferences;
    store.reset();
    store.user.preferences = preferences;
    store.seed = "onboarding";
    store.profile = clone(input.profile);
    const journeyId = uid("journey");
    const runId = startJourneyRun({ journeyId });
    store.emit("profile", "runs");
    return { runId, kind: "journey", journeyId: null };
  },
  async markDone(_journeyId, nodeKey) {
    await latency(undefined, 0.5);
    const node = store.journey()?.nodes.find((item) => item.key === nodeKey);
      if (node && (node.kind === "appointment" || node.officialUrl || node.governanceKey?.startsWith("service."))) {
      throw new ApiError({ title: "This official step needs confirmation from its provider", status: 409, code: "provider_confirmation_required" });
    }
    store.done.add(nodeKey);
    store.inProgress.delete(nodeKey);
    store.emit("journeys", "graph");
    return clone(store.journey()!);
  },
  async answerNode(_journeyId, nodeKey) {
    await latency(undefined, 0.5);
    store.answered.add(nodeKey);
    store.emit("journeys", "graph");
    return clone(store.journey()!);
  },
};

const PROCESSING_MS = 1600;
const EXTRACTION_MS = 2600;

export const mockDocuments: DocumentService = {
  async list(signal) {
    await latency(signal);
    return [...store.documents.values()].map(({ objectUrl: _objectUrl, ...doc }) => clone(doc)).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  },
  async get(id, signal) {
    await latency(signal, 0.5);
    const doc = store.documents.get(id);
    if (!doc) throw notFound("Document");
    const { objectUrl: _objectUrl, ...rest } = doc;
    return clone(rest);
  },
  async upload(file, kind) {
    await latency(undefined, 1.5);
    if (file.size > 20 * 1024 * 1024) {
      throw new ApiError({ title: "That file is too large", status: 413, code: "file_too_large", detail: "Upload a file under 20 MB." });
    }
    const doc = store.addDocument(file, kind);
    void (async () => {
      await delay(PROCESSING_MS);
      const current = store.documents.get(doc.id);
      if (!current) return;
      current.status = "processing";
      store.emit("documents", "journeys");
      await delay(EXTRACTION_MS);
      const again = store.documents.get(doc.id);
      if (!again) return;
      again.extraction = specimenExtraction(kind);
      again.status = again.extraction.fields.some((f) => f.needsReview) ? "needs_review" : "extracted";
      store.emit("documents", "journeys", "graph");
    })();
    const { objectUrl: _objectUrl, ...rest } = doc;
    return clone(rest);
  },
  async review(id, corrections) {
    await latency();
    const doc = store.documents.get(id);
    if (!doc) throw notFound("Document");
    if (doc.extraction) {
      doc.extraction.fields = doc.extraction.fields.map((field) => {
        const correction = corrections.find((c) => c.name === field.name);
        return correction ? { ...field, value: correction.value, confidence: 1, needsReview: false } : { ...field, needsReview: false };
      });
    }
    doc.status = "confirmed";
    store.emit("documents", "journeys", "graph");
    const { objectUrl: _objectUrl, ...rest } = doc;
    return clone(rest);
  },
  async remove(id) {
    await latency();
    store.removeDocument(id);
  },
};

export const mockGenerated: GeneratedDocumentService = {
  async list(signal) {
    await latency(signal);
    return clone([...store.drafts.values()]);
  },
  async approve(id) {
    await latency();
    const draft = store.drafts.get(id);
    if (!draft) throw notFound("Draft");
    draft.status = "approved";
    draft.updatedAt = new Date().toISOString();
    store.emit("generated");
    return clone(draft);
  },
  async discard(id) {
    await latency();
    const draft = store.drafts.get(id);
    if (!draft) throw notFound("Draft");
    draft.status = "discarded";
    draft.updatedAt = new Date().toISOString();
    store.emit("generated");
    return clone(draft);
  },
  async update(id, bodyMarkdown) {
    await latency();
    const draft = store.drafts.get(id);
    if (!draft) throw notFound("Draft");
    if (draft.status === "approved") {
      // Same rule as the API: an approved document is final.
      throw new ApiError({ title: "This document is already approved; ask ADAPT for a new draft to change it", status: 409, code: "generated_document_already_approved" });
    }
    draft.bodyMarkdown = bodyMarkdown;
    draft.status = "draft";
    draft.updatedAt = new Date().toISOString();
    store.emit("generated");
    return clone(draft);
  },
};

export const mockApprovals: ApprovalService = {
  async list(status, signal) {
    await latency(signal);
    return clone([...store.approvals.values()].filter((a) => !status || a.status === status).sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
  },
  async decide(id, decision) {
    await latency();
    if (!store.approvals.has(id)) throw notFound("Approval");
    return clone(store.decide(id, decision));
  },
  async actions(signal) {
    await latency(signal);
    return clone(store.actions);
  },
  async prepare(journeyNodeKey) {
    await latency(undefined, 1.4);
    const approval = store.createApproval(journeyNodeKey, null);
    if (!approval) throw new ApiError({ title: "ADAPT can't prepare this step yet", status: 409, code: "not_preparable" });
    return clone(approval);
  },
};

export const mockDiscover: DiscoverService = {
  async items(signal) {
    await latency(signal);
    return clone([...store.discoverItems.values()]);
  },
  async status(signal) {
    await latency(signal, 0.4);
    return clone(store.research);
  },
  async start() {
    await latency();
    if (!store.profile) throw new ApiError({ title: "Build your plan first", status: 409, code: "journey_required" });
    void store.startResearch();
    return clone(store.research);
  },
  async save(itemId, saved) {
    await latency(undefined, 0.4);
    const item = store.discoverItems.get(itemId);
    if (!item) throw notFound("Result");
    item.saved = saved;
    store.emit("discover");
    return clone(item);
  },
  async addToJourney(itemId) {
    await latency();
    const item = store.discoverItems.get(itemId);
    if (!item) throw notFound("Result");
    if (!store.journeyId) throw new ApiError({ title: "Build your plan first", status: 409, code: "journey_required" });
    const key = `community.${item.id}`;
    if (!store.extras.some((e) => e.key === key)) {
      store.extras.push({ key, title: item.title, summary: item.summary, url: item.source.url });
    }
    item.journeyNodeId = key;
    store.emit("discover", "journeys");
    return clone(item);
  },
  async markSeen() {
    await latency(undefined, 0.2);
    store.research = { ...store.research, seen: true };
    store.emit("discover");
  },
};

export const mockSimulate: SimulationService = {
  async variables() {
    return [
      ASSUMPTION.household,
      ASSUMPTION.children,
      ASSUMPTION.companyTiming,
      ASSUMPTION.jurisdiction,
      ASSUMPTION.arrivalDate,
      ASSUMPTION.budget,
      ASSUMPTION.housing,
    ];
  },
  async simulate(journeyId, changes: AssumptionChange[], onProgress, signal) {
    const base = store.journey();
    if (!base || base.id !== journeyId || !store.profile) throw notFound("Journey");
    const current = profileFromAssumptions(base.assumptions, store.profile);
    const next = { ...current };
    const labels: { key: string; label: string; from: string; to: string }[] = [];
    for (const change of changes) {
      const assumption = base.assumptions.find((a) => a.key === change.key);
      const field = (
        {
          "household.composition": "household",
          "household.children": "childrenCount",
          "company.timing": "companyTiming",
          "company.jurisdiction": "jurisdiction",
          "move.arrival_date": "arrivalDate",
          "budget.monthly_housing_aed": "monthlyHousingBudgetAed",
          "housing.preference": "housing",
        } as Record<string, keyof typeof next>
      )[change.key];
      if (!field) continue;
      (next as Record<string, unknown>)[field] = change.value;
      labels.push({ key: change.key, label: assumption?.label ?? change.key, from: String(assumption?.value ?? "not set"), to: String(change.value ?? "not set") });
    }

    const scenarioId = uid("scenario");
    const stages = WHAT_IF_WORKFLOW.stages;
    let scenario = base;
    const runId = startRun("what_if", async (ctx) => {
      ctx.setJourney(scenarioId);
      for (const [index, stage] of stages.entries()) {
        await ctx.stage(stage.id, stage.label, async () => {
          onProgress?.({ stage: stage.id, label: stage.label, progress: index / stages.length });
          await ctx.wait(420 + Math.random() * 260);
          if (stage.id === "dependency_analysis") {
            scenario = buildJourney(next, store.plannerProgress(), { journeyId: scenarioId, status: "scenario", parentJourneyId: base.id });
            store.scenarios.set(scenarioId, scenario);
          }
          return null;
        });
      }
      return { summary: "Scenario compared with your plan." };
    });
    store.emit("runs");

    await new Promise<void>((resolve, reject) => {
      const unsubscribe = subscribeRun(runId, {
        onEvent: (event) => {
          if (event.event === "run_completed") {
            unsubscribe();
            resolve();
          }
          if (event.event === "run_failed") {
            unsubscribe();
            reject(new ApiError({ title: "The simulation stopped", status: 500, code: "simulation_failed", detail: event.message }));
          }
        },
        onState: () => undefined,
      });
      signal?.addEventListener("abort", () => {
        unsubscribe();
        cancelRun(runId);
        reject(new DOMException("Aborted", "AbortError"));
      });
    });
    onProgress?.({ stage: "done", label: "Done", progress: 1 });
    const diff = diffJourneys(base, scenario, labels, stages.map((s) => s.id));
    return clone({ base, scenario, diff });
  },
};

/** Demo-only helpers, offered only while journeys come from mocks. */
export const mockDemo = {
  /** Loads a sample founder plan a few weeks in, with documents, drafts and approvals. */
  async seedSample() {
    await latency();
    const preferences = store.user.preferences;
    store.seedSample();
    store.user.preferences = { ...preferences, communityPersonalization: "granted" };
    const runId = startJourneyRun({ journeyId: store.journeyId!, instant: true, skipApproval: true, skipResearch: true });
    store.emit("runs", "session");
    return { runId, kind: "journey" as const, journeyId: store.journeyId };
  },
  /** Mirrors live-session preferences into mock state (consent gates mock research). */
  syncPreferences(preferences: typeof store.user.preferences) {
    store.user.preferences = { ...preferences };
  },
  reset() {
    store.reset();
  },
};

export const mockAssistant: AssistantService = {
  respond: mockRespond,
};


export { sampleProfile };
