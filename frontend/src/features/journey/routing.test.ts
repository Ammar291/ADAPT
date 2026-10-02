import { describe, expect, it } from "vitest";
import { buildTransitLayout, type PlacedNode } from "./layout";
import { roundedPath, routeEdges, simplify, type Point } from "./routing";
import { edge, journeyOf, node, sampleJourney } from "./testFixtures";

function crosses(a: Point, b: Point, rect: PlacedNode): boolean {
  const inset = 1;
  const [x1, x2] = [Math.min(a.x, b.x), Math.max(a.x, b.x)];
  const [y1, y2] = [Math.min(a.y, b.y), Math.max(a.y, b.y)];
  return x1 < rect.x + rect.width - inset && x2 > rect.x + inset && y1 < rect.y + rect.height - inset && y2 > rect.y + inset;
}

describe("routeEdges (sample plan)", () => {
  const journey = sampleJourney();
  const layout = buildTransitLayout(journey);
  const routes = routeEdges(journey, layout);

  it("routes every edge", () => {
    expect(routes.size).toBe(journey.edges.length);
  });

  it("starts at the prerequisite and ends at the step that needs it", () => {
    for (const e of journey.edges) {
      const route = routes.get(e.id)!;
      const from = layout.byKey.get(e.target)!;
      const to = layout.byKey.get(e.source)!;
      const start = route.points[0]!;
      const end = route.points.at(-1)!;
      if (route.vertical) {
        expect(start.y).toBe(from.y);
        expect(end.y).toBe(to.y + to.height);
      } else {
        expect(start).toEqual({ x: from.x + from.width, y: from.y + from.height / 2 });
        expect(end).toEqual({ x: to.x, y: to.y + to.height / 2 });
      }
    }
  });

  it("only uses horizontal and vertical segments", () => {
    for (const route of routes.values()) {
      for (let i = 1; i < route.points.length; i++) {
        const a = route.points[i - 1]!;
        const b = route.points[i]!;
        expect(a.x === b.x || a.y === b.y).toBe(true);
      }
    }
  });

  it("never passes behind a step it doesn't connect", () => {
    for (const e of journey.edges) {
      const route = routes.get(e.id)!;
      for (const placed of layout.nodes) {
        if (placed.key === e.source || placed.key === e.target) continue;
        for (let i = 1; i < route.points.length; i++) {
          expect(crosses(route.points[i - 1]!, route.points[i]!, placed), `${e.id} crosses ${placed.key}`).toBe(false);
        }
      }
    }
  });

  it("merges edges into the same step on one track", () => {
    const into = journey.edges.filter((e) => e.source === "residency.medical").map((e) => routes.get(e.id)!);
    const bent = into.filter((r) => r.points.length > 2);
    const tracks = new Set(bent.map((r) => r.points.at(-2)!.x));
    expect(tracks.size).toBe(1);
  });
});

describe("routeEdges (cases)", () => {
  it("draws a straight line between neighbours on one line", () => {
    const j = journeyOf([node("a"), node("b")], [edge("b", "a")]);
    const layout = buildTransitLayout(j);
    const route = routeEdges(j, layout).get("b>a")!;
    expect(route.points).toHaveLength(2);
  });

  it("goes around a step in the way", () => {
    // a -> c on the same line, b sits between them (b depends on a, c depends on b and a).
    const j = journeyOf([node("a"), node("b"), node("c")], [edge("b", "a"), edge("c", "b"), edge("c", "a")]);
    const layout = buildTransitLayout(j);
    const route = routeEdges(j, layout).get("c>a")!;
    const b = layout.byKey.get("b")!;
    for (let i = 1; i < route.points.length; i++) expect(crosses(route.points[i - 1]!, route.points[i]!, b)).toBe(false);
    expect(route.points.length).toBeGreaterThan(2);
  });
});

describe("path helpers", () => {
  it("simplifies repeated and collinear points", () => {
    expect(
      simplify([
        { x: 0, y: 0 },
        { x: 5, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 10 },
      ]),
    ).toEqual([
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 10 },
    ]);
  });

  it("rounds corners", () => {
    const d = roundedPath([
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
    ]);
    expect(d).toBe("M 0 0 L 88 0 Q 100 0 100 12 L 100 100");
  });
});
