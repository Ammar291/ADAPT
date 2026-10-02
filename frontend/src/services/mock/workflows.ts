import type { AgentWorkflow } from "@/domain/runs";

/**
 * Stage ids match the backend journey agent (backend/app/agents/journey), so the console
 * renders mock and live runs identically.
 */
export const JOURNEY_WORKFLOW: AgentWorkflow = {
  id: "journey",
  version: "2",
  stages: [
    { id: "intake", label: "Understand your move", description: "Reads what you said and picks out goals, household and timing.", kind: "agent", lane: 0 },
    { id: "profile_analysis", label: "Update your digital twin", description: "Records the facts you confirmed in your private graph.", kind: "tool", lane: 0 },
    { id: "document_analysis", label: "Read your documents", description: "Extracts details from your documents for you to confirm.", kind: "agent", lane: 0 },
    { id: "eligibility_analysis", label: "Check eligibility", description: "Matches your situation to the services and rules that apply.", kind: "agent", lane: 0 },
    { id: "requirement_planner", label: "Find official requirements", description: "Collects what each service needs, with its official source.", kind: "tool", lane: 0 },
    { id: "dependency_analysis", label: "Order steps by dependency", description: "Works out what must happen before what.", kind: "agent", lane: 0 },
    { id: "risk_detection", label: "Spot risks and blockers", description: "Looks for timing problems, missing documents and eligibility gaps.", kind: "agent", lane: 0 },
    { id: "document_preparation", label: "Draft documents", description: "Prepares letters, emails and checklists for your review.", kind: "agent", lane: 0 },
    { id: "action_preparation", label: "Prepare next actions", description: "Prepares official handoffs and bookings.", kind: "tool", lane: 1 },
    { id: "human_approval", label: "Your approval", description: "Nothing is sent, booked or submitted until you approve it.", kind: "human", lane: 0 },
    { id: "execution_or_handoff", label: "Hand off or carry out", description: "Carries out only what you approved, or hands you to the official site.", kind: "tool", lane: 0 },
    { id: "final_plan", label: "Your Abu Dhabi plan", description: "Brings everything together into one plan.", kind: "agent", lane: 0 },
  ],
  edges: [
    { source: "intake", target: "profile_analysis", condition: null },
    { source: "profile_analysis", target: "document_analysis", condition: null },
    { source: "document_analysis", target: "eligibility_analysis", condition: null },
    { source: "eligibility_analysis", target: "requirement_planner", condition: null },
    { source: "requirement_planner", target: "dependency_analysis", condition: null },
    { source: "dependency_analysis", target: "risk_detection", condition: null },
    { source: "risk_detection", target: "document_preparation", condition: null },
    { source: "risk_detection", target: "action_preparation", condition: null },
    { source: "document_preparation", target: "human_approval", condition: null },
    { source: "action_preparation", target: "human_approval", condition: null },
    { source: "human_approval", target: "execution_or_handoff", condition: "approved" },
    { source: "human_approval", target: "final_plan", condition: "rejected" },
    { source: "execution_or_handoff", target: "final_plan", condition: null },
  ],
};

export const WHAT_IF_WORKFLOW: AgentWorkflow = {
  id: "what_if",
  version: "1",
  stages: [
    { id: "apply_scenario", label: "Apply your what-if", description: "Copies your situation and applies the changed assumptions.", kind: "tool", lane: 0 },
    { id: "eligibility_analysis", label: "Check eligibility", description: "Re-checks which services apply.", kind: "agent", lane: 0 },
    { id: "requirement_planner", label: "Find official requirements", description: "Re-collects requirements for the new situation.", kind: "tool", lane: 0 },
    { id: "dependency_analysis", label: "Order steps by dependency", description: "Re-orders the plan.", kind: "agent", lane: 0 },
    { id: "risk_detection", label: "Spot risks and blockers", description: "Re-checks risks.", kind: "agent", lane: 0 },
    { id: "compare_scenarios", label: "Compare with your plan", description: "Lists what changed and why.", kind: "agent", lane: 0 },
  ],
  edges: [
    { source: "apply_scenario", target: "eligibility_analysis", condition: null },
    { source: "eligibility_analysis", target: "requirement_planner", condition: null },
    { source: "requirement_planner", target: "dependency_analysis", condition: null },
    { source: "dependency_analysis", target: "risk_detection", condition: null },
    { source: "risk_detection", target: "compare_scenarios", condition: null },
  ],
};

export const DIAGNOSTIC_WORKFLOW: AgentWorkflow = {
  id: "diagnostic",
  version: "1",
  stages: [
    { id: "check_store", label: "Check the database", description: "Writes and reads a test record.", kind: "tool", lane: 0 },
    { id: "check_stream", label: "Check live updates", description: "Sends progress events to this screen.", kind: "tool", lane: 0 },
    { id: "check_agent", label: "Check the agent runtime", description: "Runs a small agent step.", kind: "agent", lane: 0 },
  ],
  edges: [
    { source: "check_store", target: "check_stream", condition: null },
    { source: "check_stream", target: "check_agent", condition: null },
  ],
};

export const RESEARCH_WORKFLOW: AgentWorkflow = {
  id: "research",
  version: "1",
  stages: [{ id: "research", label: "Research community life", description: "Finds communities, events and practical tips in the background.", kind: "agent", lane: 0 }],
  edges: [],
};

export function workflowFor(kind: string): AgentWorkflow {
  switch (kind) {
    case "what_if":
      return WHAT_IF_WORKFLOW;
    case "diagnostic":
      return DIAGNOSTIC_WORKFLOW;
    case "research":
      return RESEARCH_WORKFLOW;
    default:
      return JOURNEY_WORKFLOW;
  }
}
