import { describe, expect, it } from "vitest";
import { LIFE_AREAS } from "@/domain/common";
import { depthOf } from "@/lib/journey/analysis";
import { BLOCKING_RELATIONS, LAYOUT, buildTransitLayout, columnX, roleOf, type PlacedNode } from "./layout";
import { edge, journeyOf, node, sampleJourney } from "./testFixtures";

const overlaps = (a: PlacedNode, b: PlacedNode) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

describe("buildTransitLayout (sample plan)", () => {
  const journey = sampleJourney();
  const layout = buildTransitLayout(journey);

  it("positions every node exactly once", () => {
    expect(layout.nodes).toHaveLength(journey.nodes.length);
    for (const n of journey.nodes) {
      const placed = layout.byKey.get(n.key);
      expect(placed, n.key).toBeDefined();
      expect(Number.isFinite(placed!.x) && Number.isFinite(placed!.y)).toBe(true);
    }
  });

  it("never overlaps two nodes", () => {
    for (let i = 0; i < layout.nodes.length; i++) {
      for (let j = i + 1; j < layout.nodes.length; j++) {
        const a = layout.nodes[i]!;
        const b = layout.nodes[j]!;
        expect(overlaps(a, b), `${a.key} overlaps ${b.key}`).toBe(false);
      }
    }
  });

  it("puts every prerequisite strictly left of the step that needs it", () => {
    for (const e of journey.edges.filter((x) => BLOCKING_RELATIONS.has(x.relation))) {
      const prerequisite = layout.byKey.get(e.target)!;
      const dependent = layout.byKey.get(e.source)!;
      expect(prerequisite.column, `${e.target} before ${e.source}`).toBeLessThan(dependent.column);
      expect(prerequisite.x + prerequisite.width).toBeLessThan(dependent.x);
    }
  });

  it("uses dependency depth as the column of every station", () => {
    const depth = depthOf(journey);
    for (const n of journey.nodes.filter((x) => roleOf(x.kind) === "station")) {
      expect(layout.byKey.get(n.key)!.column, n.key).toBe(depth.get(n.key));
      expect(layout.byKey.get(n.key)!.x).toBe(columnX(depth.get(n.key)!));
    }
  });

  it("orders bands by LIFE_AREAS and keeps each node inside its band", () => {
    const order = layout.bands.map((b) => LIFE_AREAS.indexOf(b.area));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    for (const placed of layout.nodes) {
      const band = layout.bands.find((b) => b.area === placed.area)!;
      expect(placed.y).toBeGreaterThanOrEqual(band.y);
      expect(placed.y + placed.height).toBeLessThanOrEqual(band.y + band.height);
    }
    const last = layout.bands.at(-1)!;
    expect(last.y + last.height).toBe(layout.height);
  });

  it("hangs satellites below their cell's station", () => {
    const cells = new Map<string, PlacedNode[]>();
    for (const placed of layout.nodes) cells.set(`${placed.column}|${placed.area}`, [...(cells.get(`${placed.column}|${placed.area}`) ?? []), placed]);
    let checked = 0;
    for (const cell of cells.values()) {
      const stations = cell.filter((n) => n.role === "station");
      if (!stations.length) continue;
      const firstStation = Math.min(...stations.map((s) => s.y));
      for (const satellite of cell.filter((n) => n.role === "satellite")) {
        expect(satellite.y, satellite.key).toBeGreaterThan(firstStation);
        checked++;
      }
    }
    expect(checked).toBeGreaterThan(0);
  });

  it("places approvals directly under the step they gate", () => {
    const approvals = layout.nodes.filter((n) => n.parentKey);
    expect(approvals.length).toBe(2);
    for (const approval of approvals) {
      const parent = layout.byKey.get(approval.parentKey!)!;
      expect(approval.column).toBe(parent.column);
      expect(approval.area).toBe(parent.area);
      expect(approval.y).toBe(parent.y + parent.height + LAYOUT.satelliteGap);
      // Centred under it, so the connector is a straight vertical line.
      expect(approval.x + approval.width / 2).toBe(parent.x + parent.width / 2);
    }
  });

  it("pulls a satellite next to the first step that needs it", () => {
    const income = layout.byKey.get("family.income")!;
    const spouseVisa = layout.byKey.get("family.spouse_visa")!;
    expect(income.column).toBe(spouseVisa.column - 1);
    // The passport is needed early, so it stays at the start.
    expect(layout.byKey.get("doc.passport")!.column).toBe(0);
  });

  it("runs each line through the first node of every cell", () => {
    for (const band of layout.bands) {
      const firstPerColumn = new Map<number, PlacedNode>();
      for (const placed of layout.nodes.filter((n) => n.area === band.area)) {
        const current = firstPerColumn.get(placed.column);
        if (!current || placed.y < current.y) firstPerColumn.set(placed.column, placed);
      }
      for (const first of firstPerColumn.values()) expect(first.y + first.height / 2, first.key).toBe(band.lineY);
    }
  });

  it("is deterministic", () => {
    const again = buildTransitLayout(sampleJourney());
    expect(again.nodes).toEqual(layout.nodes);
    expect(again.bands).toEqual(layout.bands);
  });
});

describe("buildTransitLayout (edge cases)", () => {
  it("handles an empty journey", () => {
    const layout = buildTransitLayout(journeyOf([], []));
    expect(layout.nodes).toEqual([]);
    expect(layout.bands).toEqual([]);
    expect(layout.height).toBe(0);
  });

  it("stacks several stations in one cell without overlap and grows the band", () => {
    const j = journeyOf([node("a"), node("b"), node("c"), node("d", { kind: "document" })], []);
    const layout = buildTransitLayout(j);
    const ys = ["a", "b", "c", "d"].map((k) => layout.byKey.get(k)!.y);
    expect(ys).toEqual([...ys].sort((x, y) => x - y));
    expect(new Set(ys).size).toBe(4);
    const band = layout.bands[0]!;
    expect(band.height).toBeGreaterThan(LAYOUT.bandPadTop + 3 * LAYOUT.stationHeight);
  });

  it("survives a dependency cycle", () => {
    const j = journeyOf([node("a"), node("b")], [edge("a", "b"), edge("b", "a")]);
    const layout = buildTransitLayout(j);
    expect(layout.nodes).toHaveLength(2);
  });
});
