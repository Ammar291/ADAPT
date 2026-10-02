import { describe, expect, it } from "vitest";
import { lodFor } from "./flow";
import { adjacency, emphasisCss, groupItems, matchesQuery, neighbourhood, searchItems, type ExplorerItem } from "./model";

const item = (id: string, label: string, extra: Partial<ExplorerItem> = {}): ExplorerItem => ({
  id,
  key: id,
  label,
  type: "service",
  typeLabel: "Service",
  group: "services",
  summary: null,
  aliases: [],
  rect: { x: 0, y: 0, width: 10, height: 10 },
  nodeType: "governance",
  extra: {},
  ...extra,
});

const items = [
  item("1", "Sponsor a family member's residence visa", { aliases: ["spouse visa", "wife visa"] }),
  item("2", "Get your residence visa", { aliases: ["residency"] }),
  item("3", "Passport", { type: "document", typeLabel: "Document", group: "documents" }),
  item("4", "Register a tenancy contract (Tawtheeq)", { aliases: ["rent", "lease"], summary: "Registers your lease with the municipality." }),
];

describe("searchItems", () => {
  it("ranks label prefixes first, then words, then aliases", () => {
    expect(searchItems(items, "pass").map((i) => i.id)).toEqual(["3"]);
    expect(searchItems(items, "residence").map((i) => i.id)).toEqual(["2", "1"]);
    expect(searchItems(items, "spouse").map((i) => i.id)).toEqual(["1"]);
  });

  it("matches aliases, summaries and type names, ignoring case and punctuation", () => {
    expect(searchItems(items, "RENT")[0]!.id).toBe("4");
    expect(searchItems(items, "municipality")[0]!.id).toBe("4");
    expect(searchItems(items, "document")[0]!.id).toBe("3");
    expect(searchItems(items, "member's")[0]!.id).toBe("1");
  });

  it("returns nothing for an empty query and respects the limit", () => {
    expect(searchItems(items, "  ")).toEqual([]);
    expect(searchItems(items, "e", 2)).toHaveLength(2);
  });

  it("filters the list view on every word", () => {
    expect(matchesQuery(items[0]!, "family visa")).toBe(true);
    expect(matchesQuery(items[0]!, "family passport")).toBe(false);
    expect(matchesQuery(items[0]!, "")).toBe(true);
  });
});

describe("neighbourhoods", () => {
  const edges = [
    { id: "a", source: "1", target: "2" },
    { id: "b", source: "2", target: "3" },
    { id: "c", source: "4", target: "1" },
  ];
  const adj = adjacency(edges);

  it("collects the node, its neighbours and incident edges", () => {
    const hood = neighbourhood("1", adj);
    expect([...hood.nodes].sort()).toEqual(["1", "2", "4"]);
    expect([...hood.edges].sort()).toEqual(["a", "c"]);
  });

  it("writes scoped CSS that lifts the neighbourhood", () => {
    const css = emphasisCss("kg1", "1", neighbourhood("1", adj));
    expect(css).toContain('.kg-canvas[data-kg="kg1"][data-focus] .react-flow__node:is([data-id="1"],[data-id="2"],[data-id="4"])');
    expect(css).toContain('.react-flow__edge:is([data-id="a"],[data-id="c"])');
    expect(emphasisCss("kg1", null, null)).toBe("");
  });

  it("escapes ids", () => {
    const css = emphasisCss('k"g', 'x"y', { nodes: new Set(['x"y']), edges: new Set() });
    expect(css).toContain('[data-kg="k\\"g"]');
    expect(css).toContain('[data-id="x\\"y"]');
  });
});

describe("groupItems", () => {
  it("keeps group order, sorts by label and drops empty groups", () => {
    const groups = groupItems(items, [
      { id: "documents", title: "Documents" },
      { id: "empty", title: "Empty" },
      { id: "services", title: "Services" },
    ]);
    expect(groups.map((g) => g.group.id)).toEqual(["documents", "services"]);
    expect(groups[1]!.items[0]!.label).toBe("Get your residence visa");
  });
});

describe("level of detail", () => {
  it("shows less text as the map zooms out", () => {
    expect(lodFor(1)).toBe("detail");
    expect(lodFor(0.6)).toBe("overview");
    expect(lodFor(0.4)).toBe("compact");
    expect(lodFor(0.2)).toBe("far");
  });
});
