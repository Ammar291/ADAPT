import { describe, expect, it } from "vitest";
import type { AgentWorkflow } from "@/domain/runs";
import { DIAGNOSTIC_WORKFLOW, JOURNEY_WORKFLOW } from "@/services/mock/workflows";
import { chooseOrientation, fitZoom, LAYOUT_SIZES, layoutWorkflow, stageLevels } from "./layout";

describe("stageLevels", () => {
  it("places each stage at its longest-path depth", () => {
    const levels = stageLevels(JOURNEY_WORKFLOW);
    expect(levels.get("intake")).toBe(0);
    expect(levels.get("risk_detection")).toBe(6);
    // Parallel lanes share a level.
    expect(levels.get("document_preparation")).toBe(7);
    expect(levels.get("action_preparation")).toBe(7);
    expect(levels.get("human_approval")).toBe(8);
    // final_plan waits for execution_or_handoff, not just the "rejected" shortcut.
    expect(levels.get("final_plan")).toBe(10);
  });

  it("survives a cycle", () => {
    const cyclic: AgentWorkflow = {
      id: "c",
      version: "1",
      stages: [
        { id: "a", label: "A", description: "", kind: "agent", lane: 0 },
        { id: "b", label: "B", description: "", kind: "agent", lane: 0 },
      ],
      edges: [
        { source: "a", target: "b", condition: null },
        { source: "b", target: "a", condition: null },
      ],
    };
    const levels = stageLevels(cyclic);
    expect([...levels.values()].sort()).toEqual([0, 1]);
  });
});

describe("layoutWorkflow", () => {
  it("puts levels along x and lanes along y when horizontal", () => {
    const layout = layoutWorkflow(JOURNEY_WORKFLOW, "horizontal");
    const at = (id: string) => layout.stages.find((s) => s.id === id)!;
    const { nodeWidth, nodeHeight, gapMain, gapCross } = LAYOUT_SIZES.horizontal;
    expect(at("intake")).toMatchObject({ x: 0, y: 0 });
    expect(at("profile_analysis").x).toBe(nodeWidth + gapMain);
    expect(at("document_preparation").x).toBe(at("action_preparation").x);
    expect(at("action_preparation").y).toBe(nodeHeight + gapCross);
    expect(layout.levels).toHaveLength(11);
    expect(layout.width).toBe(11 * nodeWidth + 10 * gapMain);
    expect(layout.height).toBe(2 * nodeHeight + gapCross);
  });

  it("swaps axes when vertical", () => {
    const layout = layoutWorkflow(JOURNEY_WORKFLOW, "vertical");
    const at = (id: string) => layout.stages.find((s) => s.id === id)!;
    const { nodeWidth, nodeHeight, gapMain, gapCross } = LAYOUT_SIZES.vertical;
    expect(at("profile_analysis")).toMatchObject({ x: 0, y: nodeHeight + gapMain });
    expect(at("action_preparation").x).toBe(nodeWidth + gapCross);
  });

  it("orders stages by level then lane, so keyboard order follows the flow", () => {
    const ids = layoutWorkflow(JOURNEY_WORKFLOW, "vertical").stages.map((s) => s.id);
    expect(ids.slice(0, 2)).toEqual(["intake", "profile_analysis"]);
    expect(ids.indexOf("document_preparation")).toBeLessThan(ids.indexOf("action_preparation"));
    expect(ids[ids.length - 1]).toBe("final_plan");
  });

  it("flags edges that jump over a stage in their own lane", () => {
    const edges = layoutWorkflow(JOURNEY_WORKFLOW, "vertical").edges;
    expect(edges.find((e) => e.id === "human_approval->final_plan")).toMatchObject({ skip: true, condition: "rejected" });
    expect(edges.find((e) => e.id === "human_approval->execution_or_handoff")).toMatchObject({ skip: false, condition: "approved" });
    expect(edges.find((e) => e.id === "risk_detection->action_preparation")?.skip).toBe(false);
  });

  it("branches into and merges out of a parallel lane from the side", () => {
    const edges = layoutWorkflow(JOURNEY_WORKFLOW, "vertical").edges;
    expect(edges.find((e) => e.id === "risk_detection->action_preparation")).toMatchObject({ sourceHandle: "side-out", targetHandle: "in" });
    expect(edges.find((e) => e.id === "action_preparation->human_approval")).toMatchObject({ sourceHandle: "out", targetHandle: "side-in" });
    expect(edges.find((e) => e.id === "intake->profile_analysis")).toMatchObject({ sourceHandle: "out", targetHandle: "in" });
    expect(edges.find((e) => e.id === "human_approval->final_plan")).toMatchObject({ sourceHandle: "side-out", targetHandle: "side-in" });
  });

  it("nudges stages that share a level and lane apart", () => {
    const layout = layoutWorkflow(
      {
        id: "x",
        version: "1",
        stages: [
          { id: "root", label: "", description: "", kind: "agent", lane: 0 },
          { id: "a", label: "", description: "", kind: "agent", lane: 0 },
          { id: "b", label: "", description: "", kind: "agent", lane: 0 },
        ],
        edges: [
          { source: "root", target: "a", condition: null },
          { source: "root", target: "b", condition: null },
        ],
      },
      "horizontal",
    );
    const lanes = layout.stages.filter((s) => s.level === 1).map((s) => s.lane);
    expect(lanes.sort()).toEqual([0, 1]);
  });
});

describe("orientation", () => {
  it("keeps short workflows left to right", () => {
    expect(chooseOrientation(DIAGNOSTIC_WORKFLOW, { width: 820, height: 760 })).toBe("horizontal");
  });

  it("turns long workflows top to bottom in a narrow pane", () => {
    expect(chooseOrientation(JOURNEY_WORKFLOW, { width: 820, height: 760 })).toBe("vertical");
  });

  it("uses a very wide pane left to right", () => {
    expect(chooseOrientation(JOURNEY_WORKFLOW, { width: 3200, height: 700 })).toBe("horizontal");
  });

  it("fits never zoom in past 1", () => {
    expect(fitZoom({ width: 100, height: 100 }, { width: 2000, height: 2000 })).toBe(1);
    expect(fitZoom({ width: 1000, height: 100 }, { width: 596, height: 2000 }, 48)).toBeCloseTo(0.5);
  });
});
