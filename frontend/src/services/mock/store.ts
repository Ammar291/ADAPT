/**
 * State behind the mock services.
 *
 * Privacy: profile, plan, graph, documents and consents live only in memory.
 * Only the UI language code is persisted by the central localization layer.
 */
import { resolveLocale } from "@/i18n";
import type { ActionRecord, Approval, GeneratedDocument, UserDocument } from "@/domain/documents";
import type { DiscoverItem, DiscoverSection, ResearchStatus } from "@/domain/discover";
import type { Journey } from "@/domain/journey";
import type { MoveProfile, Preferences, User } from "@/domain/profile";
import { approvalTemplate, discoverCatalogue, draftTemplates, specimenExtraction, SIMULATION_LABEL } from "./content";
import { buildJourney, type PlannerProgress } from "./planner";
import { buildUserGraph } from "./twin";
import { addDays, isoDate, uid } from "./util";

export type Topic =
  | "session"
  | "profile"
  | "journeys"
  | "runs"
  | "documents"
  | "generated"
  | "approvals"
  | "discover"
  | "graph";

const STORAGE_KEY = "adapt.mock.v1";

export interface MockDocument extends UserDocument {
  /** In-memory object URL for a file the user picked. Revoked on delete. */
  objectUrl: string | null;
}

const DEFAULT_PREFERENCES: Preferences = {
  preferredLanguage: "en",
  uiLocale: resolveLocale(),
  faithPersonalization: "not_asked",
  communityPersonalization: "not_asked",
  voiceTranscriptsRetained: false,
};

export function sampleProfile(now = new Date()): MoveProfile {
  return {
    moveType: "business",
    arrivalDate: isoDate(addDays(now, 44)),
    household: "spouse",
    childrenCount: 0,
    companyTiming: "now",
    jurisdiction: "mainland",
    languages: ["en", "ar"],
    housing: "long_lease",
    monthlyHousingBudgetAed: 9000,
    faith: null,
    note: "",
  };
}

const RESEARCH_SECTIONS: DiscoverSection[] = ["your_communities", "faith", "professional", "events", "culture", "surprises", "starter_kit"];

class MockStore {
  user: User = {
    id: "user_mock",
    displayName: "Sam Carter",
    isDemo: true,
    preferences: { ...DEFAULT_PREFERENCES },
    createdAt: new Date().toISOString(),
  };
  seed: "sample" | "onboarding" | null = null;
  profile: MoveProfile | null = null;
  journeyId: string | null = null;
  journeyCreatedAt: string | null = null;
  done = new Set<string>();
  inProgress = new Set<string>();
  answered = new Set<string>();
  extras: { key: string; title: string; summary: string; url: string | null }[] = [];
  documents = new Map<string, MockDocument>();
  drafts = new Map<string, GeneratedDocument>();
  approvals = new Map<string, Approval>();
  actions: ActionRecord[] = [];
  discoverItems = new Map<string, DiscoverItem>();
  research: ResearchStatus = emptyResearch();
  scenarios = new Map<string, Journey>();
  private listeners = new Set<(topics: Topic[]) => void>();
  private approvalListeners = new Set<(approval: Approval) => void>();

  constructor() {
    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* legacy storage unavailable */ }
  }

  // --- change notifications -----------------------------------------------------------------

  subscribe(listener: (topics: Topic[]) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(...topics: Topic[]) {
    for (const listener of this.listeners) listener(topics);
  }

  onApprovalDecided(listener: (approval: Approval) => void): () => void {
    this.approvalListeners.add(listener);
    return () => this.approvalListeners.delete(listener);
  }

  // --- persistence ----------------------------------------------------------------------------

  reset() {
    for (const doc of this.documents.values()) if (doc.objectUrl) URL.revokeObjectURL(doc.objectUrl);
    this.seed = null;
    this.profile = null;
    this.journeyId = null;
    this.journeyCreatedAt = null;
    this.done.clear();
    this.inProgress.clear();
    this.answered.clear();
    this.extras = [];
    this.documents.clear();
    this.drafts.clear();
    this.approvals.clear();
    this.actions = [];
    this.discoverItems.clear();
    this.research = emptyResearch();
    this.scenarios.clear();
    this.user.preferences = { ...DEFAULT_PREFERENCES };
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    for (const listener of this.listeners) listener(["session", "profile", "journeys", "runs", "documents", "generated", "approvals", "discover", "graph"]);
  }

  // --- seeding --------------------------------------------------------------------------------

  /** A founder moving with their spouse, a few weeks into planning. */
  seedSample() {
    this.reset();
    this.seed = "sample";
    this.profile = sampleProfile();
    this.user.preferences = { ...this.user.preferences, communityPersonalization: "granted" };
    this.journeyId = "journey_sample";
    this.journeyCreatedAt = addDays(new Date(), -6).toISOString();
    this.done = new Set(["business.trade_name"]);
    this.inProgress = new Set(["housing.search", "health.insurance"]);
    this.seedSampleDocuments();
    this.seedDrafts();
    this.createApproval("health.insurance", null, false);
    this.createApproval("housing.search", null, false);
    this.seedDiscover([]);
    this.research = {
      ...readyResearch(this.discoverItems.size),
      categories: this.researchCategories("completed"),
      personalisedWith: this.personalisedWith(),
    };
    this.emit("profile", "journeys", "documents", "generated", "approvals", "discover", "graph");
  }

  private seedSampleDocuments() {
    const at = addDays(new Date(), -5).toISOString();
    const make = (id: string, kind: MockDocument["kind"], filename: string, status: MockDocument["status"], usedFor: string[]) => {
      this.documents.set(id, {
        id,
        kind,
        filename,
        contentType: "image/jpeg",
        sizeBytes: 1_480_000,
        status,
        extraction: specimenExtraction(kind, new Date(at)),
        usedFor,
        contentUrl: null,
        objectUrl: null,
        createdAt: at,
      });
    };
    make("doc_passport", "passport", "passport-data-page.jpg", "confirmed", ["residency.entry_permit", "residency.medical", "housing.tawtheeq"]);
    make("doc_photo", "identity_document", "photo-white-background.jpg", "extracted", ["residency.entry_permit"]);
    make("doc_marriage", "marriage_certificate", "marriage-certificate.pdf", "needs_review", ["family.home_attestation"]);
    const marriage = this.documents.get("doc_marriage")!;
    marriage.contentType = "application/pdf";
  }

  private seedDrafts() {
    if (!this.profile) return;
    for (const draft of draftTemplates(this.profile, this.user.displayName, new Date(this.journeyCreatedAt ?? Date.now()))) {
      if (!this.drafts.has(draft.id)) this.drafts.set(draft.id, draft);
    }
  }

  private seedDiscover(saved: string[]) {
    if (!this.profile) return;
    this.discoverItems.clear();
    const faithGranted = this.user.preferences.faithPersonalization === "granted";
    for (const item of discoverCatalogue(this.profile, faithGranted)) {
      this.discoverItems.set(item.id, { ...item, saved: saved.includes(item.id) });
    }
  }

  researchCategories(status: "pending" | "completed"): ResearchStatus["categories"] {
    const faithGranted = this.user.preferences.faithPersonalization === "granted";
    return RESEARCH_SECTIONS.map((section) => {
      if (section === "faith" && !faithGranted) {
        return { section, status: "skipped", count: 0, reason: "faith_not_opted_in" };
      }
      const count = [...this.discoverItems.values()].filter((i) => i.section === section).length;
      return { section, status, count: status === "completed" ? count : 0, reason: null };
    });
  }

  personalisedWith(): string[] {
    const p = this.profile;
    if (!p) return [];
    const out = [`Move: ${p.moveType === "business" ? "founder" : p.moveType}`];
    if (p.household !== "alone") out.push(`Household: ${p.household.replace("_", " and ")}`);
    if (p.languages.length) out.push(`Languages: ${p.languages.length}`);
    if (p.faith && this.user.preferences.faithPersonalization === "granted") out.push("Faith: shared by you");
    return out;
  }

  // --- journey ----------------------------------------------------------------------------------

  plannerProgress(): PlannerProgress {
    const draftsByNode = new Map<string, string>();
    for (const draft of this.drafts.values()) if (draft.journeyNodeKey) draftsByNode.set(draft.journeyNodeKey, draft.id);
    return {
      done: this.done,
      inProgress: this.inProgress,
      answered: this.answered,
      documents: [...this.documents.values()],
      approvals: [...this.approvals.values()],
      draftsByNode,
    };
  }

  journey(): Journey | null {
    if (!this.profile || !this.journeyId) return null;
    const journey = buildJourney(this.profile, this.plannerProgress(), {
      journeyId: this.journeyId,
      status: "active",
      createdAt: this.journeyCreatedAt ?? undefined,
    });
    for (const extra of this.extras) {
      journey.nodes.push({
        id: extra.key,
        key: extra.key,
        kind: "task",
        title: extra.title,
        summary: extra.summary,
        whyItMatters: "You added this from Discover.",
        area: "community",
        status: this.done.has(extra.key) ? "done" : "todo",
        authority: null,
        officialUrl: null,
        estimatedDays: null,
        dueBy: null,
        completedAt: null,
        evidence: { kind: "community_web", citations: [], confidence: null, note: "From Discover. Check the source before relying on it." },
        blockers: [],
        action: extra.url
          ? { id: `act_${extra.key}`, kind: "navigate", label: "Open the source", status: null, url: extra.url, approvalId: null, draftId: null, documentKind: null, requiresUserAuthentication: false }
          : { id: `act_${extra.key}`, kind: "mark_done", label: "Mark as done", status: null, url: null, approvalId: null, draftId: null, documentKind: null, requiresUserAuthentication: false },
        governanceKey: null,
        factIds: [],
      });
    }
    return journey;
  }

  // --- approvals ----------------------------------------------------------------------------------

  createApproval(nodeKey: string, runId: string | null, notify = true): Approval | null {
    if (!this.profile) return null;
    const existing = [...this.approvals.values()].find((a) => a.journeyNodeKey === nodeKey && a.status === "pending");
    if (existing) return existing;
    const template = approvalTemplate(nodeKey, this.profile);
    if (!template) return null;
    const approval: Approval = { ...template, id: uid("appr"), actionId: uid("action"), runId };
    this.approvals.set(approval.id, approval);
    if (notify) this.emit("approvals", "journeys");
    return approval;
  }

  decide(id: string, decision: "approve" | "reject"): Approval {
    const approval = this.approvals.get(id);
    if (!approval) throw new Error("Approval not found");
    approval.status = decision === "approve" ? "approved" : "rejected";
    approval.decidedAt = new Date().toISOString();
    if (decision === "approve") {
      const draft = [...this.drafts.values()].find((d) => d.journeyNodeKey === approval.journeyNodeKey);
      if (draft && approval.actionKind === "communication") draft.status = "approved";
      this.actions.unshift({
        id: approval.actionId ?? uid("action"),
        kind: approval.actionKind,
        // Simulated adapters never claim a submission: approved messages are yours to send,
        // appointments hand off to the official booking page.
        status: approval.officialUrl ? "handoff_required" : "approved",
        title: approval.title,
        message: approval.officialUrl
          ? "Your details are ready. Finish on the official page."
          : "Approved. Send it from your own email; ADAPT can't send email from this workspace.",
        handoffUrl: approval.officialUrl,
        externalReference: null,
        confirmationSource: null,
        isSimulated: true,
        simulationLabel: SIMULATION_LABEL,
        journeyNodeKey: approval.journeyNodeKey,
        createdAt: approval.decidedAt,
      });
      if (approval.journeyNodeKey) this.inProgress.add(approval.journeyNodeKey);
    }
    for (const listener of this.approvalListeners) listener(approval);
    this.emit("approvals", "journeys", "generated");
    return approval;
  }

  // --- documents ------------------------------------------------------------------------------

  addDocument(file: File, kind: MockDocument["kind"]): MockDocument {
    const objectUrl = URL.createObjectURL(file);
    const doc: MockDocument = {
      id: uid("doc"),
      kind,
      filename: file.name || "Document",
      contentType: file.type || "application/octet-stream",
      sizeBytes: file.size,
      status: "uploaded",
      extraction: null,
      usedFor: [],
      contentUrl: objectUrl,
      objectUrl,
      createdAt: new Date().toISOString(),
    };
    this.documents.set(doc.id, doc);
    this.emit("documents", "journeys");
    return doc;
  }

  removeDocument(id: string) {
    const doc = this.documents.get(id);
    if (doc?.objectUrl) URL.revokeObjectURL(doc.objectUrl);
    this.documents.delete(id);
    this.emit("documents", "journeys", "graph");
  }

  userGraph() {
    if (!this.profile) return { nodes: [], edges: [], linkedNodes: [], generatedAt: new Date().toISOString() };
    return buildUserGraph(this.profile, [...this.documents.values()], {
      displayName: this.user.displayName,
      observedAt: this.journeyCreatedAt ?? new Date().toISOString(),
      faithGranted: this.user.preferences.faithPersonalization === "granted",
    });
  }

  // --- research -----------------------------------------------------------------------------------

  startResearch(onEvent?: (section: DiscoverSection, count: number) => void): Promise<void> {
    if (!this.profile) return Promise.resolve();
    const profile = this.profile;
    this.discoverItems.clear();
    const jobId = uid("research");
    this.research = {
      ...emptyResearch(),
      state: "running",
      jobId,
      categories: this.researchCategories("pending"),
      personalisedWith: this.personalisedWith(),
    };
    this.emit("discover");
    const faithGranted = this.user.preferences.faithPersonalization === "granted";
    const catalogue = discoverCatalogue(profile, faithGranted);
    const sections = this.research.categories.filter((c) => c.status !== "skipped").map((c) => c.section);

    return (async () => {
      for (const section of sections) {
        this.research.categories = this.research.categories.map((c) => (c.section === section ? { ...c, status: "running" } : c));
        this.emit("discover");
        await new Promise((r) => setTimeout(r, 900 + Math.random() * 700));
        const found = catalogue.filter((item) => item.section === section);
        for (const item of found) this.discoverItems.set(item.id, item);
        this.research.categories = this.research.categories.map((c) =>
          c.section === section ? { ...c, status: "completed", count: found.length } : c,
        );
        this.research.itemCount = this.discoverItems.size;
        onEvent?.(section, found.length);
        this.emit("discover");
      }
      this.research = { ...this.research, state: "ready", lastCheckedAt: new Date().toISOString(), briefReady: true, seen: false };
      this.emit("discover");
    })();
  }
}

function emptyResearch(): ResearchStatus {
  return {
    state: "idle",
    jobId: null,
    runId: null,
    mode: "snapshot",
    itemCount: 0,
    lastCheckedAt: null,
    briefReady: false,
    seen: false,
    categories: [],
    personalisedWith: [],
  };
}

function readyResearch(count: number): ResearchStatus {
  return {
    ...emptyResearch(),
    state: "ready",
    jobId: "research_sample",
    itemCount: count,
    lastCheckedAt: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    briefReady: true,
    seen: false,
  };
}

export const store = new MockStore();
