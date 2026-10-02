import { describe, expect, it } from "vitest";
import { toActionRecord, toApproval, toJourney, toResumeBody, toReview, toScenarioChanges, toScenarioDiff } from "./journeys";

const provenance = {
  kind: "official_guidance",
  citations: [{ source_url: "https://icp.gov.ae", source_title: "ICP", authority: null }],
  confidence: 0.6,
  note: null,
};

const action = {
  id: "act-1",
  type: "appointment",
  status: "awaiting_approval",
  adapter: "appointment_demo",
  title: "Medical screening appointment",
  summary: "Book 'Medical screening appointment'",
  consequences: ["DEMO / SIMULATED: the times shown are examples, not real availability."],
  service_key: "appointment.visa_screening",
  task_key: "appointment.visa_screening",
  run_id: "run-1",
  reversible: true,
  requires_human_approval: true,
  requires_user_authentication: false,
  official_url: "https://www.doh.gov.ae",
  payload: { task: "Medical screening", documents: ["Passport"], missing_documents: [] },
  is_simulated: true,
  simulation_label: "DEMO / SIMULATED",
  confirmation_source: null,
  external_reference: null,
  evidence: [],
  approval: { id: "apr-1", action_id: "act-1", run_id: "run-1", status: "pending", created_at: "2026-10-01T00:00:00Z", decided_at: null },
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const detail = {
  id: "j-1",
  title: "Founder move",
  status: "draft",
  summary: null,
  goals: ["establish_company"],
  assumptions: { "company.jurisdiction": { value: "mainland", source: "assumed", label: "where your company is licensed" } },
  considerations: [],
  nodes: [
    {
      id: "n-1", key: "appointment.visa_screening", kind: "appointment", title: "Medical screening appointment",
      summary: "", category: "health", status: "awaiting_approval", position: 1, provenance,
      blockers: [], basis: [{ key: "goals", label: "goals", fact_refs: ["f-1"] }],
      details: { why_it_matters: "Needed before: Medical fitness test.", fact_ids: ["f-1"] },
    },
    {
      id: "n-2", key: "service.family_residence_visa@spouse", kind: "task", title: "Sponsor your spouse", summary: "",
      category: "family", status: "blocked", position: 2, provenance,
      blockers: [{ kind: "dependency", message: "Waits for: Residence visa", resolution: null, related_node_key: "service.residence_visa_investor" }],
      basis: [], details: { open_questions: [{ key: "finance.monthly_income_aed", label: "monthly income (AED)" }] },
    },
  ],
  edges: [{ id: "e-1", source_node_id: "n-2", target_node_id: "n-1", relation: "depends_on", properties: { kind: "service", any_of: null } }],
  risks: [
    {
      id: "risk:timeline_dependency:x", kind: "timeline_dependency", severity: "warning", title: "Can't start at arrival",
      detail: "…", resolution: null, task_keys: ["service.family_residence_visa@spouse"], fact_keys: [], governance_keys: [],
      evidence_ids: ["ref:service.family_residence_visa"],
    },
  ],
  evidence: [{ id: "ref:service.family_residence_visa", kind: "official_reference", trust: "official_guidance", title: "ICP", source_url: "https://icp.gov.ae" }],
  requirements: [],
  eligibility: [],
  actions: [action],
  generated_documents: [],
  latest_run: null,
  pending_review: null,
  simulation_result: null,
  parent_journey_id: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

describe("toJourney", () => {
  const journey = toJourney(detail);

  it("shows the planner's goals in words", () => {
    expect(journey.goals).toEqual(["Set up your company"]);
  });

  it("maps nodes, statuses and the primary action", () => {
    const screening = journey.nodes[0]!;
    const visa = journey.nodes[1]!;
    expect(screening.status).toBe("waiting_for_me");
    expect(screening.kind).toBe("appointment");
    expect(screening.area).toBe("health");
    expect(screening.action).toMatchObject({ id: "act-1", kind: "appointment", approvalId: "apr-1", label: "Review and approve" });
    expect(screening.whyItMatters).toContain("Medical fitness");
    expect(screening.factIds).toEqual(["f-1"]);
    expect(screening.evidence.citations[0]?.url).toBe("https://icp.gov.ae");
    expect(visa.status).toBe("blocked");
    expect(visa.blockers[0]?.relatedNodeKey).toBe("service.residence_visa_investor");
    expect(visa.governanceKey).toBe("service.family_residence_visa");
    expect(visa.action).toMatchObject({ kind: "answer_question", question: "monthly income (AED)" });
  });

  it("uses node keys for edges and keeps risks and assumptions", () => {
    expect(journey.edges[0]).toMatchObject({ source: "service.family_residence_visa@spouse", target: "appointment.visa_screening" });
    expect(journey.risks[0]).toMatchObject({ kind: "timeline_dependency", nodeKeys: ["service.family_residence_visa@spouse"] });
    expect(journey.risks[0]?.evidence.kind).toBe("official_guidance");
    // The planner's facts as they are, plus the answers What if? reads in the UI's words.
    expect(journey.assumptions[0]).toEqual({ key: "company.jurisdiction", label: "where your company is licensed", value: "mainland" });
    expect(journey.assumptions.find((a) => a.key === "company.timing")?.value).toBe("now");
  });
});

describe("actions and approvals", () => {
  it("keeps the simulation label and never invents a reference", () => {
    const record = toActionRecord(action);
    expect(record.simulationLabel).toBe("DEMO / SIMULATED");
    expect(record.externalReference).toBeNull();
    const approval = toApproval(action);
    expect(approval).toMatchObject({ id: "apr-1", actionId: "act-1", gate: "action_approval", status: "pending" });
    expect(approval.payloadPreview).toEqual({ task: "Medical screening", documents: "Passport", missing_documents: "—" });
  });
});

describe("reviews", () => {
  it("maps each gate", () => {
    const approvals = toReview({
      gate: "action_approval", review_id: "rev-1", run_id: "run-1", journey_id: "j-1", title: "", summary: "",
      items: [{
        action_id: "act-1", approval_id: "apr-1", action_type: "government_portal", title: "Reserve a trade name",
        summary: "Apply", consequences: ["Opens TAMM"], payload_preview: { task: "Reserve" },
        official_url: "https://www.tamm.abudhabi", reversible: false, requires_user_authentication: true,
        is_simulated: false, simulation_label: null, task_key: "service.trade_name_reservation", evidence: [],
      }],
    });
    expect(approvals.gate).toBe("action_approval");
    if (approvals.gate === "action_approval") {
      expect(approvals.items[0]).toMatchObject({ id: "apr-1", actionId: "act-1", requiresUserAuthentication: true, simulationLabel: null, status: "pending" });
    }

    // Items already decided while the run is paused come back decided (the server reads the
    // approval rows), so the card never offers Approve twice.
    const decided = toReview({
      gate: "action_approval", review_id: "rev-1", run_id: "run-1", journey_id: "j-1", title: "", summary: "",
      items: [{
        action_id: "act-1", approval_id: "apr-1", action_type: "government_portal", title: "Reserve a trade name",
        summary: "Apply", consequences: [], payload_preview: {}, official_url: null, reversible: false,
        requires_user_authentication: true, is_simulated: false, simulation_label: null, task_key: "t", evidence: [],
        approval_status: "approved", decided_at: "2026-10-01T10:00:00Z",
      }],
    });
    if (decided.gate === "action_approval") {
      expect(decided.items[0]).toMatchObject({ status: "approved", decidedAt: "2026-10-01T10:00:00Z" });
    }

    const docs = toReview({
      gate: "document_correction", review_id: "rev-2", run_id: "run-1", journey_id: "j-1", title: "", summary: "",
      items: [{ document_id: "d-1", kind: "passport", holder: "spouse", review_task_ids: [], fields: [{ name: "passport_number", label: "Passport number", value: "Z1", confidence: 0.6, needs_review: true }] }],
    });
    expect(docs.gate === "document_correction" && docs.items[0]).toMatchObject({ holder: "Your spouse", kind: "passport" });

    const confirm = toReview({
      gate: "submission_confirmation", review_id: "rev-3", run_id: "run-1", journey_id: "j-1", title: "", summary: "",
      items: [{ action_id: "act-1", action_type: "appointment", title: "Screening", official_url: "https://www.doh.gov.ae", is_simulated: true, simulation_label: "DEMO / SIMULATED" }],
    });
    expect(confirm.gate === "submission_confirmation" && confirm.items[0]?.simulationLabel).toBe("DEMO / SIMULATED");
  });

  it("builds resume bodies in the wire format", () => {
    expect(
      toResumeBody("rev-3", {
        gate: "submission_confirmation",
        confirmations: [{ actionId: "act-1", outcome: "submitted", reference: "REF-1", note: null }],
      }),
    ).toEqual({ gate: "submission_confirmation", review_id: "rev-3", confirmations: [{ action_id: "act-1", outcome: "submitted", reference: "REF-1", note: null }] });
    expect(
      toResumeBody("rev-2", {
        gate: "document_correction",
        documents: [{ documentId: "d-1", corrections: [{ name: "passport_number", value: "Z9" }], confirm: true }],
      }),
    ).toEqual({ gate: "document_correction", review_id: "rev-2", documents: [{ document_id: "d-1", corrections: [{ name: "passport_number", value: "Z9" }], confirm: true }] });
  });
});

describe("toScenarioDiff", () => {
  it("maps the simulation result and derives node changes", () => {
    const base = toJourney(detail);
    const scenario = toJourney({ ...detail, nodes: [detail.nodes[0]!], edges: [], actions: [] });
    const diff = toScenarioDiff(
      {
        summary: "If your spouse moves: no: 1 step(s) no longer needed.",
        changes: [{ key: "household.move_with_spouse", label: "Your spouse moves to Abu Dhabi", from: true, to: false }],
        rerun_nodes: ["requirement_planner", "dependency_analysis"],
        changed_nodes: [],
        added_tasks: [],
        removed_tasks: [{ key: "service.family_residence_visa@spouse", title: "Sponsor your spouse", area: "family" }],
        changed_dependencies: [{ source: "service.family_residence_visa@spouse", target: "appointment.visa_screening", relation: "service", change: "removed" }],
        changed_risks: [{ id: "risk:x", kind: "timeline_dependency", severity: "warning", title: "t", change: "removed" }],
      },
      base,
      scenario,
    );
    expect(diff.changes[0]).toEqual({ key: "household.move_with_spouse", label: "Your spouse moves to Abu Dhabi", from: "Yes", to: "No" });
    expect(diff.rerunStages).toEqual(["requirement_planner", "dependency_analysis"]);
    expect(diff.removedTasks[0]?.area).toBe("family");
    expect(diff.changedDependencies[0]).toMatchObject({ sourceTitle: "Sponsor your spouse", targetTitle: "Medical screening appointment" });
    expect(diff.changedRisks[0]?.change).toBe("removed");
  });
});

describe("what-if in the backend's vocabulary", () => {
  const facts = {
    "household.move_with_spouse": { label: "whether your spouse is moving with you", value: true },
    "company.jurisdiction": { label: "where your company is licensed", value: "mainland" },
  };
  const plan = toJourney({ ...detail, goals: ["establish_company"], assumptions: facts });

  it("reads the plan's answers in the UI's words", () => {
    const value = (key: string) => plan.assumptions.find((a) => a.key === key)?.value;
    expect(value("household.composition")).toBe("spouse");
    expect(value("company.timing")).toBe("now");
    expect(value("company.jurisdiction")).toBe("mainland");
  });

  it("sends only scenario variables the planner knows", () => {
    expect(
      toScenarioChanges(
        [
          { key: "household.composition", value: "alone" },
          { key: "company.jurisdiction", value: "adgm" },
          { key: "move.arrival_date", value: "2027-01-15" },
        ],
        plan,
      ),
    ).toEqual([
      { key: "household.move_with_spouse", value: false },
      { key: "company.jurisdiction", value: "adgm" },
      { key: "household.planned_arrival_date", value: "2027-01-15" },
    ]);
    expect(() => toScenarioChanges([{ key: "housing.preference", value: "short_stay_first" }], plan)).toThrow();
  });
});
