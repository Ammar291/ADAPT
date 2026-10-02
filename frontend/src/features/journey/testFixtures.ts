/**
 * Journeys for unit tests only (never imported by UI code): the mock planner's sample
 * founder-with-spouse plan, and a small hand-written graph for edge cases.
 */
import type { Approval } from "@/domain/documents";
import type { Journey, JourneyEdge, JourneyNode } from "@/domain/journey";
import type { MoveProfile } from "@/domain/profile";
import { buildJourney } from "@/services/mock/planner";

const NOW = new Date("2026-09-29T09:00:00Z");

function approval(nodeKey: string): Approval {
  return {
    id: `appr_${nodeKey}`,
    actionId: null,
    runId: null,
    gate: "action_approval",
    actionKind: "communication",
    title: `Approve ${nodeKey}`,
    summary: "Test approval",
    consequences: [],
    payloadPreview: {},
    requiresUserAuthentication: false,
    reversible: false,
    officialUrl: null,
    simulationLabel: "DEMO / SIMULATED",
    status: "pending",
    journeyNodeKey: nodeKey,
    createdAt: NOW.toISOString(),
    decidedAt: null,
  };
}

export function sampleJourney(overrides: Partial<MoveProfile> = {}): Journey {
  const profile: MoveProfile = {
    moveType: "business",
    arrivalDate: "2026-11-12",
    household: "spouse",
    childrenCount: 0,
    companyTiming: "now",
    jurisdiction: "mainland",
    languages: ["en"],
    housing: "long_lease",
    monthlyHousingBudgetAed: 9000,
    faith: null,
    note: "",
    ...overrides,
  };
  return buildJourney(
    profile,
    {
      done: new Set(["business.trade_name"]),
      inProgress: new Set(["housing.search", "health.insurance"]),
      answered: new Set(),
      documents: [
        { kind: "passport", status: "confirmed" },
        { kind: "identity_document", status: "extracted" },
        { kind: "marriage_certificate", status: "needs_review" },
      ],
      approvals: [approval("health.insurance"), approval("housing.search")],
      draftsByNode: new Map(),
    },
    { journeyId: "journey_test", status: "active", now: NOW, createdAt: NOW.toISOString() },
  );
}

export function node(key: string, partial: Partial<JourneyNode> = {}): JourneyNode {
  return {
    id: key,
    key,
    kind: "task",
    title: key,
    summary: "",
    whyItMatters: null,
    area: "residency",
    status: "todo",
    authority: null,
    officialUrl: null,
    estimatedDays: 1,
    dueBy: null,
    completedAt: null,
    evidence: { kind: "ai_recommendation", citations: [], confidence: null, note: null },
    blockers: [],
    action: null,
    governanceKey: null,
    factIds: [],
    ...partial,
  };
}

export function edge(source: string, target: string, relation: JourneyEdge["relation"] = "depends_on", anyOf: string | null = null): JourneyEdge {
  return { id: `${source}>${target}`, source, target, relation, anyOf };
}

export function journeyOf(nodes: JourneyNode[], edges: JourneyEdge[]): Journey {
  return {
    id: "j",
    title: "Test",
    status: "active",
    goals: [],
    assumptions: [],
    nodes,
    edges,
    considerations: [],
    risks: [],
    parentJourneyId: null,
    createdAt: NOW.toISOString(),
    updatedAt: NOW.toISOString(),
  };
}
