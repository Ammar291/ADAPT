/**
 * Service interfaces: the seam between the UI and its data.
 *
 * Each capability has a live implementation (`./live`, the only code that talks to the API
 * and knows the wire format) and an in-memory mock (`./mock`) that produces the same domain
 * types. `./registry` picks one per capability from `config.dataMode` and the backend's
 * `/system/info` feature flags, so the UI never branches on where data comes from.
 */
import type { AssistantContext, AssistantEvent } from "@/domain/assistant";
import type { EvidenceKind } from "@/domain/common";
import type { DiscoverItem, ResearchStatus, StartResearchInput } from "@/domain/discover";
import type {
  ActionRecord,
  Approval,
  ApprovalStatus,
  DocumentKind,
  FieldCorrection,
  GeneratedDocument,
  Review,
  ReviewAnswer,
  UserDocument,
} from "@/domain/documents";
import type { KnowledgeGraph, KnowledgeNodeDetail } from "@/domain/graph";
import type { Journey, JourneySummary } from "@/domain/journey";
import type { MoveProfile, PreferencesUpdate, User } from "@/domain/profile";
import type { AgentWorkflow, RunEvent, RunKind, RunSummary, StreamState } from "@/domain/runs";
import type { AssumptionChange, ScenarioOutcome, SimulationProgress } from "@/domain/simulate";

export type Capability =
  | "session"
  | "graphs"
  | "runs"
  | "profile"
  | "journeys"
  | "documents"
  | "generated"
  | "approvals"
  | "discover"
  | "simulate"
  | "assistant"
  | "voice";

export type Source = "live" | "mock" | "unavailable";

export interface SystemFeatures {
  journeys: boolean;
  documentUpload: boolean;
  voice: boolean;
  webResearch: boolean;
  demoAuth: boolean;
  onboarding: boolean;
  discover: boolean;
  appointments: boolean;
  approvals: boolean;
  generatedDocuments: boolean;
  /** Scripted demo runs (`/demo/founder-arrival`); demo deployments only. */
  demoScenarios?: boolean;
}

export interface SystemInfo {
  appName: string;
  version: string;
  environment: string;
  demoMode: boolean;
  adapters: { capability: string; mode: "live" | "demo"; provider: string }[];
  features: SystemFeatures;
}

export interface SessionService {
  /** The signed-in user; transparently starts a private demo session where enabled. */
  me(signal?: AbortSignal): Promise<User>;
  updatePreferences(update: PreferencesUpdate): Promise<User>;
  signOut(): Promise<void>;
  systemInfo(signal?: AbortSignal): Promise<SystemInfo>;
}

export interface ProfileService {
  /** Null until onboarding is complete. */
  get(signal?: AbortSignal): Promise<MoveProfile | null>;
  save(profile: MoveProfile): Promise<MoveProfile>;
}

export interface GraphService {
  governance(params?: { types?: string[]; q?: string }, signal?: AbortSignal): Promise<KnowledgeGraph>;
  governanceNode(ref: string, signal?: AbortSignal): Promise<KnowledgeNodeDetail>;
  user(signal?: AbortSignal): Promise<KnowledgeGraph>;
}

export interface RunRef {
  runId: string;
  kind: RunKind;
  journeyId: string | null;
}

export interface RunSubscription {
  onEvent: (event: RunEvent) => void;
  onState: (state: StreamState) => void;
}

export interface RunService {
  /** Stages and edges of the agent graph for a run kind. */
  workflow(kind: RunKind, signal?: AbortSignal): Promise<AgentWorkflow>;
  get(runId: string, signal?: AbortSignal): Promise<RunSummary>;
  /** Runs started from this device in this session, newest first. */
  recent(signal?: AbortSignal): Promise<RunSummary[]>;
  /** Replays the run's events from the start, then streams live ones. Returns an unsubscribe. */
  subscribe(runId: string, subscription: RunSubscription): () => void;
  answer(runId: string, questionId: string, answer: string): Promise<RunRef>;
  /** The paused run's human checkpoint, or null when nothing is waiting. */
  review(runId: string, signal?: AbortSignal): Promise<Review | null>;
  /** Answers a document-correction or submission-confirmation review and resumes the run. */
  resume(runId: string, reviewId: string, answer: ReviewAnswer): Promise<RunRef>;
  cancel(runId: string): Promise<RunSummary>;
  startDiagnostic(): Promise<RunRef>;
}

export interface StartJourneyInput {
  /** The user's move in their own words (typed or spoken), plus onboarding answers. */
  prompt: string;
  language: string;
  channel: "text" | "voice";
  documentIds: string[];
  /** Structured onboarding answers. Live adapters send them to the profile endpoint. */
  profile: MoveProfile;
}

export interface JourneyService {
  list(signal?: AbortSignal): Promise<JourneySummary[]>;
  get(id: string, signal?: AbortSignal): Promise<Journey>;
  start(input: StartJourneyInput): Promise<RunRef>;
  /** Marks a user-completed node done (e.g. after finishing an official handoff). */
  markDone(journeyId: string, nodeKey: string): Promise<Journey>;
  /** Answers the question a node is waiting on (premises plan, income, residency route…). */
  answerNode(journeyId: string, nodeKey: string, answer: string): Promise<Journey>;
}

export interface DocumentService {
  list(signal?: AbortSignal): Promise<UserDocument[]>;
  get(id: string, signal?: AbortSignal): Promise<UserDocument>;
  upload(file: File, kind: DocumentKind): Promise<UserDocument>;
  review(id: string, corrections: FieldCorrection[]): Promise<UserDocument>;
  remove(id: string): Promise<void>;
}

export interface GeneratedDocumentService {
  list(signal?: AbortSignal): Promise<GeneratedDocument[]>;
  approve(id: string): Promise<GeneratedDocument>;
  discard(id: string): Promise<GeneratedDocument>;
  update(id: string, bodyMarkdown: string): Promise<GeneratedDocument>;
}

export interface ApprovalService {
  list(status?: ApprovalStatus, signal?: AbortSignal): Promise<Approval[]>;
  /** Approving an action lets ADAPT carry it out or hand it off; rejecting returns it to draft. */
  decide(id: string, decision: "approve" | "reject", note?: string): Promise<Approval>;
  /** Asks ADAPT to prepare an action for a journey step (e.g. an appointment booking). */
  prepare(journeyNodeKey: string): Promise<Approval>;
  actions(signal?: AbortSignal): Promise<ActionRecord[]>;
}

/**
 * Background research for Discover. Never blocks the journey.
 * Errors (as `ApiError` codes): `consent_required` (extra.consent names the consent),
 * `journey_required` (adding to a journey before one exists).
 */
export interface DiscoverService {
  items(signal?: AbortSignal): Promise<DiscoverItem[]>;
  status(signal?: AbortSignal): Promise<ResearchStatus>;
  start(input?: StartResearchInput): Promise<ResearchStatus>;
  save(itemId: string, saved: boolean): Promise<DiscoverItem>;
  addToJourney(itemId: string): Promise<DiscoverItem>;
  /** Records that the "Life Brief is ready" notice was shown, so it isn't repeated. */
  markSeen(jobId: string): Promise<void>;
}

export interface SimulationService {
  /** The assumption keys (`ASSUMPTION.*`) a what-if can change for this journey. */
  variables(journeyId: string, signal?: AbortSignal): Promise<string[]>;
  simulate(
    journeyId: string,
    changes: AssumptionChange[],
    onProgress?: (progress: SimulationProgress) => void,
    signal?: AbortSignal,
  ): Promise<ScenarioOutcome>;
}

export interface AssistantService {
  /** Streams the assistant's response to one user turn. */
  respond(text: string, context: AssistantContext, signal?: AbortSignal): AsyncIterable<AssistantEvent>;
}

export interface Services {
  sources: Record<Capability, Source>;
  /** Server-pushed invalidation (mock state changes; live SSE in future). */
  onChange?: (listener: (topics: string[]) => void) => () => void;
  session: SessionService;
  profile: ProfileService;
  graphs: GraphService;
  runs: RunService;
  journeys: JourneyService;
  documents: DocumentService;
  generated: GeneratedDocumentService;
  approvals: ApprovalService;
  discover: DiscoverService;
  simulate: SimulationService;
  /** Typed assistant turns in mock mode. Voice and live chat belong to features/voice. */
  assistant: AssistantService;
}

/** Thrown by live stubs for capabilities whose endpoint hasn't shipped. */
export class CapabilityUnavailableError extends Error {
  readonly capability: Capability;
  constructor(capability: Capability) {
    super(`${capability} isn't available yet`);
    this.name = "CapabilityUnavailableError";
    this.capability = capability;
  }
}

export type { EvidenceKind };
