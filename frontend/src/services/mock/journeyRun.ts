/**
 * The scripted journey-planning run for mock mode. It walks the same stages as the backend
 * agent, emits the same event types, creates the journey part-way through (so Home can show
 * it while the run waits for approval), and pauses at the human approval gate.
 */
import { completion, criticalPathDays } from "@/lib/journey/analysis";
import { hasSpouse, MOVE_TYPE_LABEL, HOUSEHOLD_LABEL } from "@/domain/profile";
import { citationFor } from "./governance";
import { startRun, type RunContext } from "./runEngine";
import { store } from "./store";
import { uid } from "./util";
import { JOURNEY_WORKFLOW } from "./workflows";

const label = (id: string) => JOURNEY_WORKFLOW.stages.find((s) => s.id === id)!.label;

async function tool(ctx: RunContext, node: string, tool: string, labelText: string, args: Record<string, unknown> | null, result: string, ms = 700) {
  const callId = uid("call");
  ctx.emit({ event: "tool_called", node, callId, tool, label: labelText, args });
  await ctx.wait(ms);
  ctx.emit({ event: "tool_result", node, callId, tool, summary: result, ok: true });
}

function evidence(ctx: RunContext, node: string, govKey: string) {
  const citation = citationFor(govKey);
  if (!citation) return;
  ctx.emit({ event: "evidence_found", node, title: citation.title, url: citation.url, authority: citation.authority, kind: "official_guidance" });
}

export function startJourneyRun(options: { journeyId: string; instant?: boolean; skipApproval?: boolean; skipResearch?: boolean }): string {
  return startRun(
    "journey",
    async (ctx) => {
      const profile = store.profile!;
      const spouse = hasSpouse(profile.household);
      const docs = [...store.documents.values()];

      await ctx.stage("intake", label("intake"), async () => {
        ctx.emit({ event: "node_progress", node: "intake", message: "Reading what you told ADAPT", progress: 0.3 });
        await tool(ctx, "intake", "parse_request", "Understanding your move", { channel: "text" }, `${MOVE_TYPE_LABEL[profile.moveType]}, ${HOUSEHOLD_LABEL[profile.household].toLowerCase()}`, 900);
        return profile.arrivalDate ? `Arriving ${profile.arrivalDate}` : "Flexible arrival date";
      });

      await ctx.stage("profile_analysis", label("profile_analysis"), async () => {
        await tool(ctx, "profile_analysis", "update_twin", "Updating your digital twin", null, "Facts and goals recorded", 800);
        const graph = store.userGraph();
        ctx.emit({ event: "artifact_created", node: "profile_analysis", artifactType: "twin", artifactId: "twin", title: "Your digital twin" });
        return `${graph.nodes.length} items in your twin, ${graph.edges.length} links`;
      });

      await ctx.stage("document_analysis", label("document_analysis"), async () => {
        if (!docs.length) {
          await ctx.wait(500);
          return "No documents yet. Add them any time.";
        }
        for (const doc of docs) {
          await tool(ctx, "document_analysis", "read_document", `Reading ${doc.filename}`, { document_id: doc.id }, `${doc.extraction?.fields.length ?? 0} fields`, 600);
        }
        return `${docs.length} ${docs.length === 1 ? "document" : "documents"} read`;
      });

      await ctx.stage("eligibility_analysis", label("eligibility_analysis"), async () => {
        await tool(ctx, "eligibility_analysis", "query_governance", "Matching your situation to services", { scope: "governance" }, "Services and rules that apply found", 1000);
        evidence(ctx, "eligibility_analysis", "service.residence_visa_investor");
        if (spouse) evidence(ctx, "eligibility_analysis", "eligibility_rule.family_sponsor_income");
        return spouse ? "Residency and spouse sponsorship apply" : "Residency route confirmed";
      });

      await ctx.stage("requirement_planner", label("requirement_planner"), async () => {
        await tool(ctx, "requirement_planner", "retrieve_evidence", "Checking official sources", null, "Requirements linked to their sources", 900);
        for (const key of ["service.trade_name_reservation", "service.entry_permit_investor", "service.tawtheeq", spouse ? "service.mofa_attestation" : "service.health_insurance"]) {
          evidence(ctx, "requirement_planner", key);
          await ctx.wait(250);
        }
        return "Each requirement cites its official source";
      });

      await ctx.stage("dependency_analysis", label("dependency_analysis"), async () => {
        ctx.emit({ event: "node_progress", node: "dependency_analysis", message: "Ordering your steps", progress: 0.4 });
        await tool(ctx, "dependency_analysis", "plan_dependencies", "Working out what comes first", null, "Steps ordered", 1000);
        store.journeyId = options.journeyId;
        store.journeyCreatedAt = store.journeyCreatedAt ?? new Date().toISOString();
        ctx.setJourney(options.journeyId);
        store.emit("journeys", "graph");
        const journey = store.journey()!;
        ctx.emit({ event: "artifact_created", node: "dependency_analysis", artifactType: "journey", artifactId: journey.id, title: journey.title });
        const areas = new Set(journey.nodes.map((n) => n.area)).size;
        return `${journey.nodes.length} steps across ${areas} areas`;
      });

      await ctx.stage("risk_detection", label("risk_detection"), async () => {
        await ctx.wait(800);
        const journey = store.journey()!;
        const days = criticalPathDays(journey);
        return journey.risks.length
          ? `${journey.risks.length} ${journey.risks.length === 1 ? "risk" : "risks"} found. Longest chain about ${days} days.`
          : `No risks found. Longest chain about ${days} days.`;
      });

      // Documents and actions are prepared in parallel.
      const drafts = [...store.drafts.values()];
      await Promise.all([
        ctx.stage("document_preparation", label("document_preparation"), async () => {
          for (const draft of drafts) {
            await ctx.wait(450);
            ctx.emit({ event: "document_generated", node: "document_preparation", documentId: draft.id, title: draft.title });
          }
          store.emit("generated");
          return `${drafts.length} drafts ready for your review`;
        }),
        ctx.stage("action_preparation", label("action_preparation"), async () => {
          const journey = store.journey()!;
          const handoffs = journey.nodes.filter((n) => n.action?.kind === "official_handoff" && n.status === "prepared");
          for (const node of handoffs.slice(0, 3)) {
            await ctx.wait(500);
            ctx.emit({ event: "action_prepared", node: "action_preparation", actionId: `act_${node.key}`, title: node.action!.label + ": " + node.title, kind: "official_handoff" });
          }
          if (!options.skipResearch) {
            const job = uid("research");
            ctx.emit({ event: "research_started", node: "action_preparation", jobId: job, sections: ["your_communities", "professional", "events", "culture", "surprises", "starter_kit"] });
            void store.startResearch().then(() => undefined);
          }
          return `${handoffs.length} official handoffs ready; community research started`;
        }),
      ]);

      await ctx.stage("human_approval", label("human_approval"), async () => {
        if (options.skipApproval) return "Nothing needed your approval";
        const approval = store.createApproval("health.insurance", ctx.runId);
        if (!approval || approval.status !== "pending") return "Nothing needed your approval";
        ctx.emit({ event: "approval_required", node: "human_approval", approvalId: approval.id, title: approval.title, summary: approval.summary });
        await ctx.pause({ gate: "action_approval", runId: ctx.runId, reviewId: approval.id, items: [approval] });
        const decided = store.approvals.get(approval.id)!;
        ctx.emit({ event: "approval_resolved", node: "human_approval", approvalId: approval.id, decision: decided.status === "approved" ? "approved" : "rejected" });
        return decided.status === "approved" ? "You approved 1 action" : "You declined 1 action";
      });

      await ctx.stage("execution_or_handoff", label("execution_or_handoff"), async () => {
        await tool(ctx, "execution_or_handoff", "execute_approved", "Carrying out what you approved", null, "Done, or handed to the official site", 700);
        return "Approved messages are ready for you to send";
      });

      await ctx.stage("final_plan", label("final_plan"), async () => {
        await ctx.wait(600);
        const journey = store.journey()!;
        const { total } = completion(journey);
        return `${total} steps in your plan`;
      });

      const journey = store.journey()!;
      return { summary: `Your plan is ready: ${completion(journey).total} steps, ${journey.risks.length} risks to watch.` };
    },
    { journeyId: null, instant: options.instant },
  );
}

/** Wakes the paused run when its approval is decided. */
export function wireApprovalsToRuns(resume: (runId: string) => void) {
  return store.onApprovalDecided((approval) => {
    if (!approval.runId) return;
    const pending = [...store.approvals.values()].some((a) => a.runId === approval.runId && a.status === "pending");
    if (!pending) resume(approval.runId);
  });
}
