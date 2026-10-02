/**
 * Live adapters for the journey agent: journeys, approvals, human review gates and what-if
 * simulation. The only code that knows those wire formats (`/api/journey*`, `/api/actions*`,
 * `/api/agents/{run}/review|resume`). Everything is mapped into the domain types.
 *
 * Honesty rules the UI relies on: `submitted` / `completed` only ever come from a real external
 * adapter confirmation with a reference, and simulated actions always carry
 * `simulationLabel` ("DEMO / SIMULATED").
 */
import type { Citation, Evidence, EvidenceKind, LifeArea } from "@/domain/common";
import type {
  ActionRecord,
  Approval,
  ApprovalStatus,
  DocumentCorrectionItem,
  DocumentKind,
  Review,
  ReviewAnswer,
  SubmissionConfirmationItem,
} from "@/domain/documents";
import {
  ASSUMPTION,
  type Assumption,
  type Blocker,
  type Consideration,
  type Journey,
  type JourneyEdge,
  type JourneyNode,
  type JourneyNodeKind,
  type JourneyNodeStatus,
  type JourneySummary,
  type NodeAction,
  type Risk,
} from "@/domain/journey";
import { hasChildren, hasSpouse, type Household } from "@/domain/profile";
import type { RunEvent } from "@/domain/runs";
import type { AssumptionChange, ScenarioDiff, SimulationProgress } from "@/domain/simulate";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { ApprovalService, JourneyService, RunRef, RunService, SimulationService } from "../types";
import { liveRuns } from "./foundation";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** Journey-agent routes, relative to `config.apiBaseUrl`. */
export const journeyPaths = {
  journeys: "/journey",
  journey: (id: string) => `/journey/${encodeURIComponent(id)}`,
  simulate: (id: string) => `/journey/${encodeURIComponent(id)}/simulate`,
  variables: (id: string) => `/journey/${encodeURIComponent(id)}/what-if/variables`,
  nodeDone: (id: string, key: string) =>
    `/journey/${encodeURIComponent(id)}/nodes/${encodeURIComponent(key)}/done`,
  nodeAnswer: (id: string, key: string) =>
    `/journey/${encodeURIComponent(id)}/nodes/${encodeURIComponent(key)}/answer`,
  review: (runId: string) => `/agents/${encodeURIComponent(runId)}/review`,
  resume: (runId: string) => `/agents/${encodeURIComponent(runId)}/resume`,
  run: (runId: string) => `/agents/${encodeURIComponent(runId)}`,
  actions: "/actions",
  action: (id: string) => `/actions/${encodeURIComponent(id)}`,
  prepare: "/actions/prepare",
  decide: (actionId: string, decision: "approve" | "reject") =>
    `/actions/${encodeURIComponent(actionId)}/${decision}`,
} as const;

// --- shared mapping -------------------------------------------------------------------------------

const LIFE_AREAS = new Set(["business", "residency", "family", "housing", "health", "finance", "daily_life", "community"]);
const NODE_KINDS = new Set(["task", "requirement", "document", "appointment", "dependency", "approval", "action"]);
const DOC_KINDS = new Set(["passport", "marriage_certificate", "employment_letter", "business_document", "tenancy_document", "identity_document", "miscellaneous"]);

/** Server journey-node status -> the UI's one progress vocabulary. */
const NODE_STATUS: Record<string, JourneyNodeStatus> = {
  ready: "todo",
  blocked: "blocked",
  needs_info: "waiting_for_me",
  in_progress: "in_progress",
  awaiting_approval: "waiting_for_me",
  handoff: "prepared",
  done: "done",
  not_applicable: "not_applicable",
};

/** The planner's goal keys, in the words the UI uses (the same as the mock planner's). */
const GOAL_LABEL: Record<string, string> = {
  establish_company: "Set up your company",
  residency: "Get your residence visa",
  sponsor_family: "Sponsor your family",
  find_housing: "Find a home",
};

function goalLabel(goal: unknown): string {
  const key = String(goal);
  return GOAL_LABEL[key] ?? key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

const ACTION_LABEL: Record<string, string> = {
  draft: "Prepare again",
  prepared: "Prepared",
  awaiting_approval: "Review and approve",
  approved: "Prepared",
  handoff_required: "Official handoff",
  submitted: "Submitted",
  completed: "Completed",
  blocked: "Blocked",
  failed: "Try again",
  rejected: "Prepare again",
  cancelled: "Prepare again",
};

function area(value: unknown): LifeArea {
  return (typeof value === "string" && LIFE_AREAS.has(value) ? value : "daily_life") as LifeArea;
}

function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function toCitation(raw: Raw): Citation {
  return {
    title: raw.source_title ?? raw.title ?? raw.source_url ?? "",
    url: raw.source_url ?? raw.url ?? "",
    authority: raw.authority ?? null,
    retrievedAt: raw.retrieved_at ?? null,
    section: raw.section_or_page ?? raw.section ?? null,
    quote: raw.quote ?? raw.claim ?? null,
    excerpt: raw.excerpt,
    effectiveDate: raw.effective_date ?? null,
    freshness: raw.freshness,
    sourceFamily: raw.source_family ?? null,
    chunkId: raw.chunk_id ?? raw.rag_chunk_id ?? null,
  };
}

function toProvenance(raw: Raw | null | undefined): Evidence {
  return {
    kind: (raw?.kind ?? "ai_recommendation") as EvidenceKind,
    citations: (raw?.citations ?? []).map(toCitation),
    confidence: raw?.confidence ?? null,
    note: raw?.note ?? null,
  };
}

/** Evidence built from the agent's evidence records (by id), strongest tier first. */
function evidenceFrom(ids: string[], records: Map<string, Raw>): Evidence {
  const found = ids.map((id) => records.get(id)).filter((r): r is Raw => Boolean(r && r.source_url));
  const order: EvidenceKind[] = ["authoritative_requirement", "official_guidance", "community_web", "ai_recommendation"];
  const kind = order.find((k) => found.some((r) => r.trust === k)) ?? "ai_recommendation";
  return { kind, citations: found.map(toCitation), confidence: null, note: null };
}

function payloadPreview(payload: Raw | null | undefined): Record<string, string> {
  return Object.fromEntries(
    Object.entries(payload ?? {}).map(([key, value]) => [
      key,
      Array.isArray(value) ? value.map(display).join(", ") || "—" : display(value),
    ]),
  );
}

// --- actions & approvals ----------------------------------------------------------------------------

/** approval id -> action id, learned from every approval this adapter has seen. */
const actionIdByApproval = new Map<string, string>();

export function toActionRecord(raw: Raw): ActionRecord {
  const verified = raw.confirmation_source === "adapter" && raw.is_simulated !== true &&
    typeof raw.external_reference === "string" && raw.external_reference.trim().length > 0;
  const status = ["submitted", "completed"].includes(raw.status) && !verified
    ? (raw.official_url ? "handoff_required" : "prepared") : raw.status;
  return {
    id: raw.id,
    kind: raw.type,
    status,
    title: raw.title,
    message: raw.summary ?? "",
    handoffUrl: raw.official_url ?? null,
    externalReference: verified ? raw.external_reference : null,
    confirmationSource: verified ? raw.confirmation_source : null,
    isSimulated: raw.is_simulated === true,
    simulationLabel: raw.simulation_label ?? (raw.is_simulated ? "DEMO / SIMULATED" : null),
    journeyNodeKey: raw.task_key ?? null,
    createdAt: raw.created_at,
  };
}

/** An ActionOut (with its embedded approval) as the Approval the Review UI renders. */
export function toApproval(action: Raw): Approval {
  const approval: Raw = action.approval ?? {};
  if (approval.id) actionIdByApproval.set(approval.id, action.id);
  return {
    id: approval.id ?? action.id,
    actionId: action.id,
    runId: approval.run_id ?? action.run_id ?? null,
    gate: "action_approval",
    actionKind: action.type,
    title: action.title,
    summary: action.summary ?? "",
    consequences: action.consequences ?? [],
    payloadPreview: payloadPreview(action.payload),
    requiresUserAuthentication: action.requires_user_authentication === true,
    reversible: action.reversible === true,
    officialUrl: action.official_url ?? null,
    simulationLabel: action.simulation_label ?? (action.is_simulated ? "DEMO / SIMULATED" : null),
    status: (approval.status ?? "pending") as ApprovalStatus,
    journeyNodeKey: action.task_key ?? null,
    createdAt: approval.created_at ?? action.created_at,
    decidedAt: approval.decided_at ?? null,
  };
}

async function actionIdFor(approvalId: string): Promise<string> {
  const known = actionIdByApproval.get(approvalId);
  if (known) return known;
  const actions = await api.get<Raw[]>(journeyPaths.actions, { query: { limit: 500 } });
  const match = actions.find((a) => a.approval?.id === approvalId || a.id === approvalId);
  if (!match) throw new ApiError({ status: 404, title: "That approval no longer exists", code: "approval_not_found" });
  actionIdByApproval.set(approvalId, match.id);
  return match.id;
}

// --- journeys -----------------------------------------------------------------------------------

function nodeAction(node: Raw, action: Raw | undefined, draft: Raw | undefined): NodeAction | null {
  if (action) {
    const record = toActionRecord(action);
    return {
      id: action.id,
      kind: action.type,
      label: action.type === "appointment" && ["prepared", "approved"].includes(record.status)
        ? "Ready to book" : ACTION_LABEL[record.status] ?? "Open",
      status: record.status,
      url: action.official_url ?? null,
      approvalId: action.approval?.id ?? null,
      draftId: null,
      documentKind: null,
      requiresUserAuthentication: action.requires_user_authentication === true,
    };
  }
  if (draft) {
    return {
      id: draft.id, kind: "review_draft", label: `Review: ${draft.title}`, status: null, url: null,
      approvalId: null, draftId: draft.id, documentKind: null, requiresUserAuthentication: false,
    };
  }
  const question: Raw | undefined = (node.details?.open_questions ?? [])[0];
  if (question) {
    return {
      id: `${node.key}:answer`, kind: "answer_question", label: "Answer", status: null, url: null,
      approvalId: null, draftId: null, documentKind: null, requiresUserAuthentication: false,
      question: question.question ?? question.label ?? question.key,
    };
  }
  const actionType: string | undefined = node.details?.action_type;
  if (node.status === "ready" && actionType && node.official_url) {
    // Ready to act on but not prepared yet: ApprovalService.prepare(node.key) prepares it.
    return {
      id: `${node.key}:prepare`, kind: actionType as NodeAction["kind"], label: "Prepare",
      status: null, url: node.official_url, approvalId: null, draftId: null, documentKind: null,
      requiresUserAuthentication: node.details?.requires_login === true,
    };
  }
  const missing = (node.blockers ?? []).find((b: Raw) => b.kind === "missing_document");
  if (missing) {
    return {
      id: `${node.key}:upload`, kind: "upload_document", label: "Add the document", status: null, url: null,
      approvalId: null, draftId: null, documentKind: missing.related_document ?? null, requiresUserAuthentication: false,
    };
  }
  return null;
}

export function toJourney(raw: Raw): Journey {
  const keyById = new Map<string, string>((raw.nodes ?? []).map((n: Raw) => [n.id, n.key]));
  const actionByTask = new Map<string, Raw>();
  for (const action of raw.actions ?? []) if (action.task_key) actionByTask.set(action.task_key, action);
  const draftByNode = new Map<string, Raw>();
  for (const doc of raw.generated_documents ?? []) if (doc.journey_node_id) draftByNode.set(doc.journey_node_id, doc);
  const records = new Map<string, Raw>((raw.evidence ?? []).map((e: Raw) => [e.id, e]));

  const nodes: JourneyNode[] = (raw.nodes ?? []).map((n: Raw) => {
    const details: Raw = n.details ?? {};
    const factIds: string[] = details.fact_ids ?? (n.basis ?? []).flatMap((b: Raw) => b.fact_refs ?? []);
    const action = actionByTask.get(n.key);
    const actionStatus = action ? toActionRecord(action).status : null;
    const status = n.status === "done" && actionStatus && actionStatus !== "completed"
      ? (actionStatus === "handoff_required" ? "handoff" : "ready") : n.status;
    return {
      id: n.id,
      key: n.key,
      kind: (NODE_KINDS.has(n.kind) ? n.kind : "task") as JourneyNodeKind,
      title: n.title,
      summary: n.summary ?? "",
      whyItMatters: details.why_it_matters ?? null,
      area: area(n.category),
      status: NODE_STATUS[status] ?? "todo",
      authority: n.authority ?? null,
      officialUrl: n.official_url ?? null,
      estimatedDays: n.estimated_duration_days ?? null,
      dueBy: n.due_by ?? null,
      completedAt: null,
      evidence: toProvenance(n.provenance),
      blockers: (n.blockers ?? []).map(
        (b: Raw): Blocker => ({
          kind: b.kind,
          message: b.message,
          resolution: b.resolution ?? null,
          relatedNodeKey: b.related_node_key ?? null,
        }),
      ),
      action: nodeAction(n, actionByTask.get(n.key), draftByNode.get(n.id)),
      governanceKey: String(n.key).split("@")[0] ?? null,
      factIds: [...new Set(factIds)],
      questions: ((details.open_questions ?? []) as Raw[]).map((q) => ({
        key: String(q.key),
        label: String(q.label ?? q.key),
        question: String(q.question ?? q.label ?? q.key),
      })),
    };
  });

  const edges: JourneyEdge[] = (raw.edges ?? []).map((e: Raw) => ({
    id: e.id,
    source: keyById.get(e.source_node_id) ?? e.source_node_id,
    target: keyById.get(e.target_node_id) ?? e.target_node_id,
    relation: "depends_on",
    anyOf: e.properties?.any_of ?? null,
  }));

  const risks: Risk[] = (raw.risks ?? []).map((r: Raw) => ({
    id: r.id,
    kind: r.kind,
    title: r.title,
    detail: r.detail,
    resolution: r.resolution ?? null,
    severity: r.severity,
    nodeKeys: r.task_keys ?? [],
    evidence: evidenceFrom(r.evidence_ids ?? [], records),
  }));

  const facts = (raw.assumptions ?? {}) as Record<string, Raw>;
  const assumptions: Assumption[] = Object.entries(facts).map(([key, fact]) => ({ key, label: fact.label ?? key, value: fact.value }));
  for (const derived of uiAssumptions(facts, raw.goals ?? [])) {
    if (!assumptions.some((a) => a.key === derived.key)) assumptions.push(derived);
  }

  for (const action of raw.actions ?? []) if (action.approval?.id) actionIdByApproval.set(action.approval.id, action.id);

  return {
    id: raw.id,
    title: raw.title,
    status: raw.status,
    goals: ((raw.goals ?? []) as unknown[]).map(goalLabel),
    assumptions,
    nodes,
    edges,
    considerations: (raw.considerations ?? []).map(
      (c: Raw): Consideration => ({
        id: c.id,
        title: c.title,
        detail: c.detail ?? "",
        area: area(c.area),
        evidence: evidenceFrom(c.evidence_ids ?? [], records),
      }),
    ),
    risks,
    parentJourneyId: raw.parent_journey_id ?? null,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

/**
 * The plan's facts in the UI's assumption vocabulary (`ASSUMPTION.*`, what onboarding asks
 * and What if? changes), derived from the planner's facts. `company.jurisdiction` is the
 * same key in both.
 */
function uiAssumptions(facts: Record<string, Raw>, goals: unknown[]): Assumption[] {
  const value = (key: string) => facts[key]?.value;
  const out: Assumption[] = [];
  const spouse = value("household.move_with_spouse") ?? value("household.has_spouse");
  const children = Number(value("household.children_count") ?? 0) || 0;
  if (spouse !== undefined || children) {
    const household: Household = spouse === true ? (children ? "spouse_children" : "spouse") : children ? "children" : "alone";
    out.push({ key: ASSUMPTION.household, label: "Who's moving", value: household });
    out.push({ key: ASSUMPTION.children, label: "Children", value: children });
  }
  const arrival = value("household.planned_arrival_date");
  if (typeof arrival === "string") out.push({ key: ASSUMPTION.arrivalDate, label: "Target arrival", value: arrival });
  out.push({ key: ASSUMPTION.companyTiming, label: "Your company", value: goals.includes("establish_company") ? "now" : "none" });
  return out;
}

/** UI assumption keys the backend can simulate, by the backend's scenario variable. */
const SIMULATED_AS: Record<string, string> = {
  "household.move_with_spouse": ASSUMPTION.household,
  "household.children_count": ASSUMPTION.children,
  "household.planned_arrival_date": ASSUMPTION.arrivalDate,
  "company.jurisdiction": ASSUMPTION.jurisdiction,
};

/** What if? changes (UI vocabulary) as the backend's scenario changes. */
export function toScenarioChanges(changes: AssumptionChange[], base: Journey): { key: string; value: unknown }[] {
  const out = new Map<string, unknown>();
  const before = (key: string) => base.assumptions.find((a) => a.key === key)?.value;
  for (const change of changes) {
    switch (change.key) {
      case ASSUMPTION.household: {
        const household = change.value as Household;
        out.set("household.move_with_spouse", hasSpouse(household));
        if (!hasChildren(household) && Number(before(ASSUMPTION.children) ?? 0) > 0) out.set("household.children_count", 0);
        break;
      }
      case ASSUMPTION.children:
        out.set("household.children_count", Number(change.value));
        break;
      case ASSUMPTION.arrivalDate:
        // "Flexible" isn't something to simulate: there is no date to plan backwards from.
        if (typeof change.value === "string" && change.value) out.set("household.planned_arrival_date", change.value);
        break;
      case ASSUMPTION.jurisdiction:
        out.set("company.jurisdiction", change.value);
        break;
      default:
        throw new ApiError({ status: 422, title: "ADAPT can't simulate that change yet", code: "unsupported_change" });
    }
  }
  if (!out.size) throw new ApiError({ status: 422, title: "Choose a date to compare with your plan", code: "nothing_to_simulate" });
  return [...out].map(([key, value]) => ({ key, value }));
}

function toSummary(raw: Raw): JourneySummary {
  return {
    id: raw.id,
    title: raw.title,
    status: raw.status,
    nodeCount: raw.node_count ?? 0,
    completedCount: raw.completed_node_count ?? 0,
    updatedAt: raw.updated_at,
  };
}

async function activeJourneyId(): Promise<string> {
  const list = await api.get<Raw[]>(journeyPaths.journeys);
  const active = list.find((j) => j.status !== "scenario" && j.status !== "archived");
  if (!active) throw new ApiError({ status: 404, title: "Start a journey first", code: "journey_not_found" });
  return active.id;
}

export const liveJourneys: JourneyService = {
  async list(signal) {
    return (await api.get<Raw[]>(journeyPaths.journeys, { signal })).map(toSummary);
  },
  async get(id, signal) {
    return toJourney(await api.get<Raw>(journeyPaths.journey(id), { signal }));
  },
  async start(input) {
    // Onboarding answers are saved by the profile service; the journey agent reads them
    // from the user's twin (planning facts), so only the request itself is sent here.
    const started = await api.post<Raw>(journeyPaths.journeys, {
      prompt: input.prompt,
      language: input.language,
      channel: input.channel,
      document_ids: input.documentIds,
    });
    return { runId: started.run.id, kind: "journey", journeyId: started.journey_id };
  },
  async markDone(journeyId, nodeKey) {
    return toJourney(await api.post<Raw>(journeyPaths.nodeDone(journeyId, nodeKey)));
  },
  /** Answers the node's most decisive open question (see `details.open_questions`). */
  async answerNode(journeyId, nodeKey, answer) {
    return toJourney(await api.post<Raw>(journeyPaths.nodeAnswer(journeyId, nodeKey), { answer }));
  },
};

export const liveApprovals: ApprovalService = {
  async list(status, signal) {
    const actions = await api.get<Raw[]>(journeyPaths.actions, { query: { approval: status }, signal });
    return actions.filter((a) => a.approval).map(toApproval);
  },
  async decide(id, decision, note) {
    const actionId = await actionIdFor(id);
    const result = await api.post<Raw>(journeyPaths.decide(actionId, decision), note ? { note } : {});
    return toApproval(result.action);
  },
  async prepare(journeyNodeKey) {
    const prepared = await api.post<Raw>(journeyPaths.prepare, {
      journey_id: await activeJourneyId(),
      task_key: journeyNodeKey,
    });
    return toApproval({ ...prepared.action, approval: prepared.approval });
  },
  async actions(signal) {
    return (await api.get<Raw[]>(journeyPaths.actions, { signal })).map(toActionRecord);
  },
};

// --- human review gates -------------------------------------------------------------------------------

const HOLDER: Record<string, string> = { self: "You", spouse: "Your spouse" };

export function toReview(raw: Raw): Review {
  const base = { runId: raw.run_id, reviewId: raw.review_id };
  switch (raw.gate) {
    case "action_approval":
      return {
        ...base,
        gate: "action_approval",
        items: (raw.items ?? []).map((i: Raw) =>
          toApproval({
            id: i.action_id,
            type: i.action_type,
            title: i.title,
            summary: i.summary,
            consequences: i.consequences,
            payload: i.payload_preview,
            requires_user_authentication: i.requires_user_authentication,
            reversible: i.reversible,
            official_url: i.official_url,
            is_simulated: i.is_simulated,
            simulation_label: i.simulation_label,
            task_key: i.task_key,
            run_id: raw.run_id,
            created_at: i.decided_at ?? new Date().toISOString(),
            // What the person already decided on this paused run (the server reads the
            // approval rows), so a decided card never offers Approve again.
            approval: { id: i.approval_id, status: i.approval_status ?? "pending", run_id: raw.run_id, decided_at: i.decided_at ?? null },
          }),
        ),
      };
    case "document_correction":
      return {
        ...base,
        gate: "document_correction",
        items: (raw.items ?? []).map(
          (i: Raw): DocumentCorrectionItem => ({
            documentId: i.document_id,
            kind: (DOC_KINDS.has(i.kind) ? i.kind : "miscellaneous") as DocumentKind,
            holder: HOLDER[i.holder] ?? (i.holder ? `Your ${String(i.holder).replace(/\d+$/, "")}` : null),
            fields: (i.fields ?? []).map((f: Raw) => ({
              name: f.name,
              label: f.label ?? f.name,
              value: f.value ?? null,
              confidence: typeof f.confidence === "number" ? f.confidence : 0,
              needsReview: f.needs_review === true,
            })),
          }),
        ),
      };
    default:
      return {
        ...base,
        gate: "submission_confirmation",
        items: (raw.items ?? []).map(
          (i: Raw): SubmissionConfirmationItem => ({
            actionId: i.action_id,
            kind: i.action_type,
            title: i.title,
            officialUrl: i.official_url ?? null,
            simulationLabel: i.simulation_label ?? null,
          }),
        ),
      };
  }
}

export function toResumeBody(reviewId: string, answer: ReviewAnswer): Raw {
  if (answer.gate === "document_correction") {
    return {
      gate: answer.gate,
      review_id: reviewId,
      documents: answer.documents.map((d) => ({
        document_id: d.documentId,
        corrections: d.corrections.map((c) => ({ name: c.name, value: c.value })),
        confirm: d.confirm,
      })),
    };
  }
  return {
    gate: answer.gate,
    review_id: reviewId,
    confirmations: answer.confirmations.map((c) => ({
      action_id: c.actionId,
      outcome: c.outcome,
      reference: c.reference || null,
      note: c.note || null,
    })),
  };
}

export const liveJourneyRuns: Pick<RunService, "review" | "resume"> = {
  async review(runId, signal) {
    try {
      return toReview(await api.get<Raw>(journeyPaths.review(runId), { signal }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },
  async resume(runId, reviewId, answer): Promise<RunRef> {
    const accepted = await api.post<Raw>(journeyPaths.resume(runId), toResumeBody(reviewId, answer));
    return { runId, kind: accepted.run?.kind ?? "journey", journeyId: accepted.run?.journey_id ?? null };
  },
};

// --- what-if -----------------------------------------------------------------------------------------

/** Stages a what-if can run: apply, up to six re-run stages, compare. */
const WHAT_IF_STAGES = 8;
const POLL_MS = 2000;

export interface WhatIfVariable {
  key: string;
  label: string;
  type: "boolean" | "enum" | "number" | "integer" | "date";
  options: string[];
  current: unknown;
}

export async function liveWhatIfVariables(journeyId: string, signal?: AbortSignal): Promise<WhatIfVariable[]> {
  return api.get<WhatIfVariable[]>(journeyPaths.variables(journeyId), { signal });
}

/** Resolves when the run finishes: progress over SSE, completion confirmed by polling. */
function waitForRun(runId: string, onEvent: (event: RunEvent) => void, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    let done = false;
    let unsubscribe = () => {};
    const finish = (error?: unknown) => {
      if (done) return;
      done = true;
      clearInterval(timer);
      unsubscribe();
      signal?.removeEventListener("abort", onAbort);
      if (error) reject(error);
      else resolve();
    };
    const onAbort = () => finish(new DOMException("Aborted", "AbortError"));
    signal?.addEventListener("abort", onAbort);
    try {
      unsubscribe = liveRuns.subscribe(runId, {
        onEvent: (event) => {
          onEvent(event);
          if (event.event === "run_completed") finish();
          if (event.event === "run_failed") finish(new ApiError({ status: 422, title: event.message, code: event.code }));
        },
        onState: () => {},
      });
    } catch {
      // No EventSource (e.g. tests): polling alone decides.
    }
    const timer = setInterval(async () => {
      try {
        const run = await api.get<Raw>(journeyPaths.run(runId), { signal });
        if (run.status === "succeeded") finish();
        if (run.status === "failed" || run.status === "cancelled") {
          finish(
            new ApiError({
              status: 422,
              title: run.error?.detail ?? "The what-if didn't finish",
              code: run.error?.code ?? "run_failed",
            }),
          );
        }
      } catch (error) {
        if (signal?.aborted) finish(error);
      }
    }, POLL_MS);
  });
}

export function toScenarioDiff(result: Raw, base: Journey, scenario: Journey): ScenarioDiff {
  const titles = new Map<string, string>([...base.nodes, ...scenario.nodes].map((n) => [n.key, n.title]));
  const before = new Map(base.nodes.map((n) => [n.key, n]));
  const dependsOn = (journey: Journey, key: string) =>
    journey.edges.filter((e) => e.source === key).map((e) => e.target).sort().join(",");
  const changedNodes = scenario.nodes.flatMap((node) => {
    const old = before.get(node.key);
    if (!old) return [];
    const fields: string[] = [];
    if (old.status !== node.status) fields.push("status");
    if (dependsOn(base, node.key) !== dependsOn(scenario, node.key)) fields.push("dependencies");
    if (old.blockers.length !== node.blockers.length) fields.push("blockers");
    return fields.length ? [{ key: node.key, title: node.title, fields }] : [];
  });
  return {
    summary: result.summary ?? "",
    changes: (result.changes ?? []).map((c: Raw) => ({ key: c.key, label: c.label, from: display(c.from), to: display(c.to) })),
    rerunStages: result.rerun_nodes ?? [],
    changedNodes,
    addedTasks: (result.added_tasks ?? []).map((t: Raw) => ({ key: t.key, title: t.title, area: area(t.area) })),
    removedTasks: (result.removed_tasks ?? []).map((t: Raw) => ({ key: t.key, title: t.title, area: area(t.area) })),
    changedDependencies: (result.changed_dependencies ?? []).map((d: Raw) => ({
      source: d.source,
      target: d.target,
      sourceTitle: titles.get(d.source) ?? d.source,
      targetTitle: titles.get(d.target) ?? d.target,
      relation: d.relation,
      change: d.change,
    })),
    changedRisks: (result.changed_risks ?? []).map((r: Raw) => ({
      id: r.id, kind: r.kind, title: r.title, severity: r.severity, change: r.change,
    })),
  };
}

export const liveSimulate: SimulationService = {
  async variables(journeyId, signal) {
    const variables = await liveWhatIfVariables(journeyId, signal);
    return variables.flatMap((v) => (SIMULATED_AS[v.key] ? [SIMULATED_AS[v.key]!] : []));
  },
  async simulate(journeyId, changes, onProgress, signal) {
    const plan = toJourney(await api.get<Raw>(journeyPaths.journey(journeyId), { signal }));
    const started = await api.post<Raw>(journeyPaths.simulate(journeyId), { changes: toScenarioChanges(changes, plan) }, { signal });
    let finished = 0;
    await waitForRun(
      started.run.id,
      (event) => {
        if (!onProgress || !event.node) return;
        if (event.event === "node_started") {
          onProgress({ stage: event.node, label: event.label, progress: Math.min(finished / WHAT_IF_STAGES, 0.95) } satisfies SimulationProgress);
        }
        if (event.event === "node_completed") {
          finished += 1;
          onProgress({ stage: event.node, label: event.label ?? event.summary ?? event.node, progress: Math.min(finished / WHAT_IF_STAGES, 0.95) });
        }
      },
      signal,
    );
    const [baseRaw, scenarioRaw] = await Promise.all([
      api.get<Raw>(journeyPaths.journey(journeyId), { signal }),
      api.get<Raw>(journeyPaths.journey(started.scenario_journey_id), { signal }),
    ]);
    const base = toJourney(baseRaw);
    const scenario = toJourney(scenarioRaw);
    onProgress?.({ stage: "compare_scenarios", label: "Compared with your plan", progress: 1 });
    return { base, scenario, diff: toScenarioDiff(scenarioRaw.simulation_result ?? scenarioRaw.simulation ?? {}, base, scenario) };
  },
};
