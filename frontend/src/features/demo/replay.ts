import { tr } from "@/i18n";
import raw from "./replay.json";

// Public synthetic fixtures only. The builder records real graph and reader output;
// no personal input, credentials, phone numbers or live booking confirmations belong here.
export const replay = raw;
export const DEMO_STORAGE_KEY = "adapt.stage.v1";
export const RESEARCH_DURATION_MS = 9_000;
export const SCENES = [tr("copy.meet_c8b4225", { lng: "en" }), tr("copy.documents_687c828", { lng: "en" }), tr("copy.your_twin_19ff5ed", { lng: "en" }), tr("copy.governance_823619e", { lng: "en" }), tr("copy.agents_64acf7e", { lng: "en" }), tr("copy.requirement_e9c366b", { lng: "en" }), tr("copy.handoff_09496b0", { lng: "en" }), tr("copy.research_be601df", { lng: "en" }), tr("copy.what_if_da957c3", { lng: "en" }), tr("copy.your_plan_b96ddaa", { lng: "en" })];
export interface DemoProgress {
  version: 1;
  scene: number;
  intro: boolean;
  documents: boolean;
  agentStartedAt: number | null;
  researchStartedAt: number | null;
  decision: "pending" | "approved" | "rejected";
  alone: boolean;
}
export function initialProgress(): DemoProgress {
  return { version: 1, scene: 0, intro: false, documents: false, agentStartedAt: null, researchStartedAt: null, decision: "pending", alone: false };
}
export function readProgress(storage: Pick<Storage, "getItem"> | null): DemoProgress {
  try {
    const p = JSON.parse(storage?.getItem(DEMO_STORAGE_KEY) ?? "null") as Partial<DemoProgress> | null;
    if (!p || p.version !== 1) return initialProgress();
    return {
      version: 1,
      scene: Number.isInteger(p.scene) && p.scene! >= 0 && p.scene! < SCENES.length ? p.scene! : 0,
      intro: p.intro === true, documents: p.documents === true, alone: p.alone === true,
      agentStartedAt: typeof p.agentStartedAt === "number" && Number.isFinite(p.agentStartedAt) ? p.agentStartedAt : null,
      researchStartedAt: typeof p.researchStartedAt === "number" && Number.isFinite(p.researchStartedAt) ? p.researchStartedAt : null,
      decision: p.decision === "approved" || p.decision === "rejected" ? p.decision : "pending",
    };
  } catch { return initialProgress(); }
}
export function writeProgress(storage: Pick<Storage, "setItem"> | null, p: DemoProgress): void {
  // Explicit projection: arbitrary text can never be persisted by this helper.
  try { storage?.setItem(DEMO_STORAGE_KEY, JSON.stringify(readProgress({ getItem: () => JSON.stringify(p) }))); } catch { /* Storage disabled: demo still works. */ }
}
export function researchProgress(startedAt: number | null, now: number): number {
  return startedAt === null ? 0 : Math.max(0, Math.min(1, (now - startedAt) / RESEARCH_DURATION_MS));
}
export const adapterActions = replay.tasks.filter((t) => t.action_type !== null);
export const blockers = replay.risks.filter((r) => r.kind === "missing_information");
export const agentStages = replay.events.filter((e) => e.event === "node_started")
  .filter((e, i, all) => all.findIndex((other) => other.node === e.node) === i);
export const featuredTasks = ["service.company_registration_adgm", "service.residence_visa_investor", "service.tawtheeq", tr("copy.service_family_residence_visa_spouse_80e319f", { lng: "en" }), "appointment.uae_mission_visit", "service.mofa_attestation"];
export function branchChanges() {
  const keys = new Set(replay.branch.tasks.map((t) => t.key));
  const dependencies = new Set(replay.branch.dependencies.map((d) => `${d.task}<-${d.depends_on}`));
  return {
    removedTasks: replay.tasks.filter((t) => !keys.has(t.key)),
    removedDependencies: replay.dependencies.filter((d) => !dependencies.has(`${d.task}<-${d.depends_on}`)),
  };
}
export const INTRO_REPLY = tr("copy.absolutely_let_s_make_this_manageable_i_ll_conne_72e9208", { lng: "en" });
export function scriptedAnswer(topic: "first" | "blockers" | "connect") {
  if (topic === "first") return tr("copy.start_with_the_company_application_and_your_marr_4425204");
  if (topic === "blockers") return tr("copy.two_eligibility_questions_need_your_answer_the_c_470938a");
  return tr("copy.the_background_brief_brings_together_indian_comm_1eec9be");
}
