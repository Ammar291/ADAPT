import { describe, expect, it } from "vitest";
import { countByFilter, criticalPath } from "@/lib/journey/analysis";
import {
  anyOfSizes,
  clampViewport,
  criticalEdges,
  edgeVisual,
  filterMatches,
  focusSet,
  initialViewport,
  listGroups,
  neighbour,
  nodeEmphasis,
  parseFilter,
  type EdgeContext,
} from "./graph";
import { buildTransitLayout } from "./layout";
import { edge, journeyOf, node, sampleJourney } from "./testFixtures";

describe("filters", () => {
  it("parses the URL filter, defaulting to all", () => {
    expect(parseFilter("blocked")).toBe("blocked");
    expect(parseFilter("waiting_for_me")).toBe("waiting_for_me");
    expect(parseFilter("nonsense")).toBe("all");
    expect(parseFilter(null)).toBe("all");
  });

  it("matches the counts shown on the filter control", () => {
    const journey = sampleJourney();
    const counts = countByFilter(journey);
    expect(filterMatches(journey, "all")).toBeNull();
    expect(filterMatches(journey, "blocked")!.size).toBe(counts.blocked);
    expect(filterMatches(journey, "todo")!.size).toBe(counts.todo);
  });

  it("dims nodes that don't match, and keeps matching ones", () => {
    const journey = sampleJourney();
    const matches = filterMatches(journey, "blocked");
    const blocked = journey.nodes.find((n) => n.status === "blocked")!;
    const done = journey.nodes.find((n) => n.status === "done")!;
    expect(nodeEmphasis(blocked.key, null, matches)).toBe("normal");
    expect(nodeEmphasis(done.key, null, matches)).toBe("dimmed");
    expect(nodeEmphasis(done.key, null, null)).toBe("normal");
  });
});

describe("focusSet", () => {
  //  a <- b <- c <- d ; x unrelated ; e approves c
  const j = journeyOf(
    [node("a"), node("b"), node("c"), node("d"), node("x"), node("e", { kind: "approval" })],
    [edge("b", "a"), edge("c", "b", "requires"), edge("d", "c"), edge("c", "e", "approves")],
  );

  it("includes the whole prerequisite chain, direct unlocks and attached approvals", () => {
    const focus = focusSet(j, "c");
    expect([...focus.upstream].sort()).toEqual(["a", "b", "e"]);
    expect([...focus.unlocks]).toEqual(["d"]);
    expect(focus.nodes.has("x")).toBe(false);
    expect(focus.edges).toEqual(new Set(["b>a", "c>b", "d>c", "c>e"]));
  });

  it("emphasises the focused node, relates its chain and dims the rest", () => {
    const focus = focusSet(j, "c");
    expect(nodeEmphasis("c", focus, null)).toBe("focused");
    expect(nodeEmphasis("a", focus, null)).toBe("related");
    expect(nodeEmphasis("x", focus, null)).toBe("dimmed");
  });
});

describe("edgeVisual", () => {
  const j = journeyOf(
    [
      node("done", { status: "done" }),
      node("open", { status: "waiting_for_me" }),
      node("blockedA", { status: "blocked" }),
      node("blockedB", { status: "blocked" }),
      node("free"),
      node("alt1"),
      node("alt2"),
    ],
    [
      edge("blockedA", "open"),
      edge("blockedB", "blockedA"),
      edge("free", "done", "requires"),
      edge("free", "alt1", "depends_on", "g"),
      edge("free", "alt2", "depends_on", "g"),
      edge("open", "done", "blocked_by"),
    ],
  );
  const ctx = (over: Partial<EdgeContext> = {}): EdgeContext => ({
    nodes: new Map(j.nodes.map((n) => [n.key, n])),
    critical: new Set(),
    focus: null,
    matches: null,
    anyOfSizes: anyOfSizes(j),
    ...over,
  });
  const byId = (id: string) => j.edges.find((e) => e.id === id)!;

  it("styles relations by line pattern", () => {
    expect(edgeVisual(byId("free>alt1"), ctx()).dash).toBeUndefined();
    expect(edgeVisual(byId("free>done"), ctx()).dash).toBeDefined();
    expect(edgeVisual(byId("open>done"), ctx()).tone).toBe("danger");
  });

  it("marks the cause of a block as danger and a passed-down block as soft", () => {
    expect(edgeVisual(byId("blockedA>open"), ctx()).tone).toBe("danger");
    expect(edgeVisual(byId("blockedB>blockedA"), ctx()).tone).toBe("danger-soft");
  });

  it("draws the critical path in teal, thicker", () => {
    const visual = edgeVisual(byId("blockedB>blockedA"), ctx({ critical: new Set(["blockedB>blockedA"]) }));
    expect(visual.tone).toBe("critical");
    expect(visual.width).toBeGreaterThan(edgeVisual(byId("free>alt1"), ctx()).width);
  });

  it("draws edges from met prerequisites quietly", () => {
    expect(edgeVisual(byId("free>done"), ctx()).tone).toBe("settled");
    expect(edgeVisual(byId("free>alt1"), ctx()).tone).toBe("base");
  });

  it("only labels alternatives of the same step 'either'", () => {
    const k = journeyOf([node("x"), node("y"), node("p")], [edge("x", "p", "depends_on", "g"), edge("y", "p", "depends_on", "g")]);
    const c = { ...ctx(), nodes: new Map(k.nodes.map((n) => [n.key, n])), anyOfSizes: anyOfSizes(k) };
    expect(edgeVisual(k.edges[0]!, c).label).toBeNull();
  });

  it("labels alternatives 'either'", () => {
    expect(edgeVisual(byId("free>alt1"), ctx()).label).toBe("either");
    expect(edgeVisual(byId("free>done"), ctx()).label).toBeNull();
  });

  it("puts the focused chain in ink and dims unrelated edges", () => {
    const focus = focusSet(j, "blockedA");
    expect(edgeVisual(byId("blockedA>open"), ctx({ focus })).tone).toBe("focus");
    expect(edgeVisual(byId("free>alt1"), ctx({ focus })).dimmed).toBe(true);
  });

  it("dims edges that leave the filtered set", () => {
    const matches = new Set(["blockedA", "blockedB"]);
    expect(edgeVisual(byId("blockedB>blockedA"), ctx({ matches })).dimmed).toBe(false);
    expect(edgeVisual(byId("blockedA>open"), ctx({ matches })).dimmed).toBe(true);
  });
});

describe("criticalEdges", () => {
  it("links consecutive critical-path steps", () => {
    const journey = sampleJourney();
    const path = criticalPath(journey);
    const edges = criticalEdges(journey, path);
    expect(edges.size).toBeGreaterThan(0);
    expect(edges.size).toBeLessThanOrEqual(path.length - 1);
    for (const id of edges) {
      const e = journey.edges.find((x) => x.id === id)!;
      expect(path.indexOf(e.target) + 1).toBe(path.indexOf(e.source));
    }
  });
});

describe("neighbour", () => {
  const grid = [
    { key: "a", x: 0, y: 0, width: 10, height: 10 },
    { key: "b", x: 100, y: 0, width: 10, height: 10 },
    { key: "c", x: 100, y: 100, width: 10, height: 10 },
    { key: "d", x: 0, y: 100, width: 10, height: 10 },
  ];
  it("moves to the nearest node in the arrow's direction", () => {
    expect(neighbour(grid, "a", "right")).toBe("b");
    expect(neighbour(grid, "a", "down")).toBe("d");
    expect(neighbour(grid, "c", "left")).toBe("d");
    expect(neighbour(grid, "c", "up")).toBe("b");
    expect(neighbour(grid, "a", "left")).toBeNull();
    expect(neighbour(grid, "missing", "left")).toBeNull();
  });
});

describe("listGroups", () => {
  const journey = sampleJourney();
  const layout = buildTransitLayout(journey);

  it("filters for real", () => {
    const groups = listGroups(journey, layout, "blocked", "area");
    const nodes = groups.flatMap((g) => g.nodes);
    expect(nodes.length).toBe(countByFilter(journey).blocked);
    expect(nodes.every((n) => n.status === "blocked")).toBe(true);
  });

  it("groups by area in line order, earliest steps first", () => {
    const groups = listGroups(journey, layout, "all", "area");
    expect(groups[0]!.id).toBe("business");
    for (const g of groups) {
      const cols = g.nodes.map((n) => layout.byKey.get(n.key)!.column);
      expect(cols).toEqual([...cols].sort((a, b) => a - b));
    }
  });

  it("groups by stage in order", () => {
    const groups = listGroups(journey, layout, "all", "stage");
    expect(groups[0]!.title).toBe("Stage 1");
    const total = groups.reduce((sum, g) => sum + g.nodes.length, 0);
    expect(total).toBe(countByFilter(journey).all);
  });
});

describe("initialViewport", () => {
  it("fits a small map, centred", () => {
    const v = initialViewport({ width: 500, height: 300 }, { width: 1000, height: 600 });
    expect(v.zoom).toBe(1);
    expect(v.x).toBe(250);
  });

  it("anchors a large map at the start of its lines at a readable zoom", () => {
    const v = initialViewport({ width: 3000, height: 2000 }, { width: 1000, height: 600 }, { minZoom: 0.6 });
    expect(v).toEqual({ x: 0, y: 0, zoom: 0.6 });
  });

  it("fits the width of a tall map and starts at the top", () => {
    const v = initialViewport({ width: 1000, height: 3000 }, { width: 848, height: 600 }, { padding: 24, minZoom: 0.6 });
    expect(v.zoom).toBeCloseTo(0.8);
    expect(v.y).toBe(0);
    expect(v.x).toBeCloseTo(24);
  });
});

describe("clampViewport", () => {
  const content = { width: 2000, height: 1500 };
  const area = { right: 800, bottom: 600, top: 40 };
  it("doesn't pan past the start of the lines or the top", () => {
    expect(clampViewport({ x: 300, y: 200, zoom: 1 }, content, area)).toEqual({ x: 0, y: 40, zoom: 1 });
  });
  it("doesn't pan past the end of the map", () => {
    expect(clampViewport({ x: -5000, y: -5000, zoom: 1 }, content, area)).toEqual({ x: 800 - 2000 - 24, y: 600 - 1500 - 24, zoom: 1 });
  });
  it("leaves a viewport inside the bounds alone", () => {
    expect(clampViewport({ x: -400, y: -300, zoom: 1 }, content, area)).toEqual({ x: -400, y: -300, zoom: 1 });
  });
  it("pins a map smaller than the area to its start", () => {
    expect(clampViewport({ x: 100, y: 100, zoom: 0.2 }, content, area)).toEqual({ x: 0, y: 40, zoom: 0.2 });
  });
});
