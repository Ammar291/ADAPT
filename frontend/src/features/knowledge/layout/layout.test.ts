import { describe, expect, it } from "vitest";
import { chooseRows, columnLayout, orderHub, type ColumnSpec, type LayoutEdge, type LayoutNode } from "./columns";
import { boundsOf, centerOf, exitPoint, overlaps, packPositions, routeBetween, straightBetween, type Rect } from "./geometry";
import { circularMean, radialLayout, spreadAngles } from "./radial";

function noOverlaps(rects: Rect[], margin = 0): boolean {
  return rects.every((r, i) => rects.every((o, j) => j <= i || !overlaps(r, o, margin)));
}

describe("packPositions", () => {
  it("keeps positions that are already far enough apart", () => {
    expect(packPositions([0, 100, 200], 50)).toEqual([0, 100, 200]);
  });

  it("pushes crowded positions apart around their mean", () => {
    const out = packPositions([100, 100, 100], 20);
    expect(out).toEqual([80, 100, 120]);
  });

  it("respects bounds and the minimum gap", () => {
    const out = packPositions([-50, -40, 0], 30, 0, 200);
    expect(out[0]).toBe(0);
    out.slice(1).forEach((y, i) => expect(y - out[i]!).toBeGreaterThanOrEqual(30 - 1e-9));
    expect(Math.max(...out)).toBeLessThanOrEqual(200);
  });

  it("returns nothing for nothing", () => {
    expect(packPositions([], 10)).toEqual([]);
  });
});

describe("edge routes", () => {
  const a: Rect = { x: 0, y: 0, width: 100, height: 40 };
  it("joins facing sides of side-by-side boxes", () => {
    const route = routeBetween(a, { x: 200, y: 100, width: 100, height: 40 });
    expect(route.path.startsWith("M100,20 C")).toBe(true);
    expect(route.path.endsWith("200,120")).toBe(true);
    expect(route.label.x).toBeGreaterThan(100);
    expect(route.label.x).toBeLessThan(200);
  });

  it("goes right to left when the target is on the left", () => {
    const route = routeBetween({ x: 300, y: 0, width: 100, height: 40 }, a);
    expect(route.path.startsWith("M300,20")).toBe(true);
    expect(route.path.endsWith("100,20")).toBe(true);
  });

  it("uses a short vertical connector for stacked neighbours", () => {
    const route = routeBetween(a, { x: 0, y: 54, width: 100, height: 40 }, { gap: 14 });
    expect(route.path.startsWith("M50,40")).toBe(true);
    expect(route.path.endsWith("50,54")).toBe(true);
  });

  it("arcs outside the column for boxes further apart in the same column", () => {
    const route = routeBetween(a, { x: 0, y: 300, width: 100, height: 40 }, { side: "left", gap: 14 });
    expect(route.path.startsWith("M0,20")).toBe(true);
    const xs = [...route.path.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((m) => Number(m[1]));
    expect(Math.min(...xs)).toBeLessThan(0);
  });

  it("clips straight edges to the box outlines", () => {
    const b: Rect = { x: 300, y: 0, width: 100, height: 40 };
    const route = straightBetween(a, b);
    expect(route.path).toBe("M100,20 L300,20");
    expect(exitPoint(a, { x: 50, y: 500 })).toEqual({ x: 50, y: 40 });
  });

  it("measures bounds", () => {
    expect(boundsOf([a, { x: -10, y: 5, width: 20, height: 100 }])).toEqual({ x: -10, y: 0, width: 110, height: 105 });
    expect(centerOf(a)).toEqual({ x: 50, y: 20 });
  });
});

const columns: ColumnSpec[] = [
  { id: "docs", title: "Documents", types: ["document"], width: 100, height: 40 },
  { id: "services", title: "Services", types: ["service"], width: 120, height: 48, hub: true },
  { id: "authorities", title: "Authorities", types: ["authority"], width: 100, height: 40 },
];

function chain(): { nodes: LayoutNode[]; edges: LayoutEdge[] } {
  const nodes: LayoutNode[] = [
    { id: "s1", type: "service", label: "A licence" },
    { id: "s2", type: "service", label: "B visa" },
    { id: "s3", type: "service", label: "C family visa" },
    { id: "s4", type: "service", label: "D unrelated" },
    { id: "d1", type: "document", label: "Passport" },
    { id: "d2", type: "document", label: "Licence" },
    { id: "a1", type: "authority", label: "ICP" },
    { id: "a2", type: "authority", label: "ADDED" },
    { id: "x1", type: "mystery", label: "Unknown kind" },
  ];
  const edges: LayoutEdge[] = [
    { id: "e1", source: "s3", target: "s2", relation: "depends_on" },
    { id: "e2", source: "s2", target: "s1", relation: "depends_on" },
    { id: "e3", source: "s2", target: "d1", relation: "requires" },
    { id: "e4", source: "s3", target: "d1", relation: "requires" },
    { id: "e5", source: "s1", target: "d2", relation: "produces" },
    { id: "e6", source: "a1", target: "s2", relation: "provides" },
    { id: "e7", source: "a1", target: "s3", relation: "provides" },
    { id: "e8", source: "a2", target: "s1", relation: "provides" },
    { id: "e9", source: "s1", target: "missing", relation: "requires" },
  ];
  return { nodes, edges };
}

describe("columnLayout", () => {
  it("puts each kind in its column, left to right, with unknown kinds in the hub", () => {
    const { nodes, edges } = chain();
    const layout = columnLayout(nodes, edges, { columns, aspect: 1.6 });
    expect(layout.columnOf.get("d1")).toBe("docs");
    expect(layout.columnOf.get("x1")).toBe("services");
    const xOf = (id: string) => layout.nodes.get(id)!.x;
    expect(xOf("d1")).toBeLessThan(xOf("s1"));
    expect(xOf("s1")).toBeLessThan(xOf("a1"));
    expect(layout.columns.map((c) => c.id)).toEqual(["docs", "services", "authorities"]);
    expect(layout.columns.find((c) => c.id === "services")!.count).toBe(5);
  });

  it("never overlaps boxes and routes every valid edge", () => {
    const { nodes, edges } = chain();
    const layout = columnLayout(nodes, edges, { columns, aspect: 1.6 });
    expect(layout.nodes.size).toBe(nodes.length);
    expect(noOverlaps([...layout.nodes.values()])).toBe(true);
    expect([...layout.edges.keys()].sort()).toEqual(["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"]);
    for (const r of layout.nodes.values()) {
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.y + r.height).toBeLessThanOrEqual(layout.bounds.height + 1e-6);
    }
  });

  it("places nodes level with the hub nodes they connect to", () => {
    const { nodes, edges } = chain();
    const layout = columnLayout(nodes, edges, { columns, aspect: 1.6 });
    const cy = (id: string) => centerOf(layout.nodes.get(id)!).y;
    // ICP provides the two visas, ADDED the licence: their order follows the services.
    expect(cy("a2") < cy("a1")).toBe(cy("s1") < cy("s2"));
  });

  it("is deterministic", () => {
    const { nodes, edges } = chain();
    const one = columnLayout(nodes, edges, { columns, aspect: 1.6 });
    const two = columnLayout([...nodes].reverse(), [...edges].reverse(), { columns, aspect: 1.6 });
    expect([...two.nodes.entries()].sort()).toEqual([...one.nodes.entries()].sort());
  });

  it("wraps tall columns into sub-columns for wide viewports", () => {
    const nodes: LayoutNode[] = Array.from({ length: 30 }, (_, i) => ({ id: `s${i}`, type: "service", label: `Service ${String(i).padStart(2, "0")}` }));
    const wide = columnLayout(nodes, [], { columns, aspect: 2 });
    const tall = columnLayout(nodes, [], { columns, aspect: 0.5 });
    expect(wide.columns[0]!.subColumns).toBeGreaterThan(tall.columns[0]!.subColumns);
    expect(noOverlaps([...wide.nodes.values()])).toBe(true);
  });
});

describe("chooseRows", () => {
  it("prefers more rows for tall viewports", () => {
    const gaps = { row: 10, sub: 20, column: 80, header: 40 };
    const cols = [{ width: 100, height: 40 }];
    expect(chooseRows([40], cols, 0.5, gaps)).toBeGreaterThan(chooseRows([40], cols, 3, gaps));
  });
});

describe("orderHub", () => {
  it("keeps a dependency chain together, prerequisites first", () => {
    const hub: LayoutNode[] = [
      { id: "z", type: "service", label: "Zeta (final step)" },
      { id: "m", type: "service", label: "Mid step" },
      { id: "a", type: "service", label: "Alpha (first step)" },
      { id: "q", type: "service", label: "Quiet unrelated" },
    ];
    const edges: LayoutEdge[] = [
      { id: "1", source: "z", target: "m", relation: "depends_on" },
      { id: "2", source: "m", target: "a", relation: "depends_on" },
    ];
    const order = orderHub(hub, edges, new Map(), 1);
    const at = (id: string) => order.indexOf(id);
    expect(Math.abs(at("z") - at("m"))).toBe(1);
    expect(Math.abs(at("m") - at("a"))).toBe(1);
  });
});

describe("radial layout", () => {
  const nodes: LayoutNode[] = [
    { id: "you", type: "person", label: "You" },
    { id: "spouse", type: "person", label: "Your spouse" },
    { id: "g1", type: "goal", label: "Get my residence visa" },
    { id: "g2", type: "goal", label: "Sponsor my spouse" },
    { id: "d1", type: "document", label: "Passport" },
    { id: "p1", type: "preference", label: "Languages" },
    { id: "pub1", type: "service", label: "Residence visa" },
    { id: "pub2", type: "service", label: "Family visa" },
    { id: "pub3", type: "document", label: "Passport (public)" },
  ];
  const edges: LayoutEdge[] = [
    { id: "a", source: "you", target: "spouse", relation: "spouse_of" },
    { id: "b", source: "you", target: "g1", relation: "has_goal" },
    { id: "c", source: "you", target: "g2", relation: "has_goal" },
    { id: "d", source: "you", target: "d1", relation: "holds_document" },
    { id: "e", source: "you", target: "p1", relation: "prefers" },
    { id: "f", source: "g1", target: "pub1", relation: "pursues" },
    { id: "g", source: "g2", target: "pub2", relation: "pursues" },
    { id: "h", source: "d1", target: "pub3", relation: "satisfies" },
  ];
  const publics = new Set(["pub1", "pub2", "pub3"]);
  const options = {
    centerId: "you",
    aspect: 1.8,
    ring: (n: LayoutNode) => (publics.has(n.id) ? 3 : n.type === "person" ? 1 : 2) as 1 | 2 | 3,
    size: (n: LayoutNode) => (publics.has(n.id) ? { width: 170, height: 48 } : { width: 180, height: 44 }),
  };

  it("centres the person and puts rings outside each other", () => {
    const layout = radialLayout(nodes, edges, options);
    expect(centerOf(layout.nodes.get("you")!)).toEqual({ x: 0, y: 0 });
    expect(layout.ringOf.get("spouse")).toBe(1);
    expect(layout.ringOf.get("g1")).toBe(2);
    expect(layout.ringOf.get("pub1")).toBe(3);
    expect(layout.rings[1]!.ry).toBeLessThan(layout.rings[2]!.ry);
    expect(layout.rings[2]!.ry).toBeLessThan(layout.rings[3]!.ry);
    expect(layout.rings[3]!.rx).toBeGreaterThan(layout.rings[3]!.ry);
  });

  it("never overlaps nodes and routes every edge", () => {
    const layout = radialLayout(nodes, edges, options);
    expect(noOverlaps([...layout.nodes.values()], 4)).toBe(true);
    expect(layout.edges.size).toBe(edges.length);
  });

  it("places public rules near the twin nodes that link to them", () => {
    const layout = radialLayout(nodes, edges, options);
    const angle = (id: string) => {
      const c = centerOf(layout.nodes.get(id)!);
      const r = id.startsWith("pub") ? layout.rings[3]! : layout.rings[2]!;
      return Math.atan2(c.y / r.ry, c.x / r.rx);
    };
    const diff = (a: number, b: number) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
    expect(diff(angle("pub1"), angle("g1"))).toBeLessThan(0.6);
    expect(diff(angle("pub3"), angle("d1"))).toBeLessThan(0.6);
  });

  it("copes with a twin that is only the person", () => {
    const layout = radialLayout([nodes[0]!], [], options);
    expect(layout.nodes.size).toBe(1);
    expect(layout.bounds.width).toBe(180);
  });
});

describe("angles", () => {
  it("spreads crowded angles at least `sep` apart, in order", () => {
    const out = spreadAngles([0, 0.01, 0.02], 0.3);
    expect(out[1]! - out[0]!).toBeGreaterThanOrEqual(0.3 - 1e-9);
    expect(out[2]! - out[1]!).toBeGreaterThanOrEqual(0.3 - 1e-9);
  });

  it("averages angles across the wrap-around", () => {
    const mean = circularMean([Math.PI - 0.1, -Math.PI + 0.1])!;
    expect(Math.abs(Math.abs(mean) - Math.PI)).toBeLessThan(1e-9);
    expect(circularMean([])).toBeNull();
  });
});
