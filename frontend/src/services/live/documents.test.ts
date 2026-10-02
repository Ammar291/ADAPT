import { describe, expect, it } from "vitest";
import { toCorrections, toDocument } from "./documents";
import { factsByAttribute, toUserGraph } from "./userGraph";

const detail = {
  id: "d1",
  kind: "marriage_certificate",
  filename: "cert.pdf",
  content_type: "application/pdf",
  size_bytes: 1200,
  status: "needs_review",
  created_at: "2026-09-29T10:00:00Z",
  processed_at: "2026-09-29T10:00:05Z",
  content_url: "/api/documents/d1/content?expires=1&sig=abc",
  warnings: [],
  fields: [
    { name: "spouse_2_name", label: "Second spouse", value: "Priya Mehta", confidence: 0.9, needs_review: false },
    { name: "date_of_marriage", label: "Date of marriage", value: "2019-11-23", value_display: "23 November 2019", confidence: 0.9, needs_review: false },
    { name: "attested", label: "Attested", value: null, confidence: 0.5, needs_review: true },
  ],
  review_tasks: [
    { id: "t1", message: "Check the attested (document)", fact: { id: "f3" } },
    { id: "t2", message: "This looks like a passport", fact: null },
  ],
};

describe("live documents mapping", () => {
  it("maps fields with display values and review flags", () => {
    const doc = toDocument(detail);
    expect(doc.status).toBe("needs_review");
    expect(doc.contentUrl).toBe("/api/documents/d1/content?expires=1&sig=abc");
    expect(doc.extraction?.fields.map((f) => [f.name, f.value, f.needsReview])).toEqual([
      ["spouse_2_name", "Priya Mehta", false],
      ["date_of_marriage", "23 November 2019", false],
      ["attested", null, true],
    ]);
    // Document-level tasks surface as warnings; fact tasks stay on their fields.
    expect(doc.extraction?.warnings).toEqual(["This looks like a passport"]);
  });

  it("keeps list items metadata-only and never exposes a deleted status", () => {
    const doc = toDocument({ ...detail, fields: undefined, content_url: undefined, status: "deleted" });
    expect(doc.extraction).toBeNull();
    expect(doc.contentUrl).toBeNull();
    expect(doc.status).toBe("failed");
  });

  it("sends empty corrections as removals", () => {
    expect(toCorrections([{ name: "attested", value: "" }, { name: "x", value: "yes" }])).toEqual([
      { name: "attested", value: null },
      { name: "x", value: "yes" },
    ]);
  });
});

describe("live user graph mapping", () => {
  it("prefers accepted facts and marks every edge private", () => {
    const facts = factsByAttribute([
      { attribute: "full_name", status: "needs_review", value: "Pr1ya", confidence: 0.4, source: "document_extracted" },
      { attribute: "full_name", status: "accepted", value: "Priya Mehta", confidence: 1, source: "user_stated", confirmed_by_user: true },
      { attribute: "married_on", status: "needs_review", value: null, confidence: 0.3, source: "document_extracted" },
      { attribute: "marriage_country", status: "needs_review", value: "IND", confidence: 0.6, source: "document_extracted", source_document_id: "d1" },
    ]);
    expect(facts.full_name?.value).toBe("Priya Mehta");
    expect(facts.married_on).toBeUndefined();
    expect(facts.marriage_country?.sourceRef).toBe("document:d1");

    const graph = toUserGraph({
      nodes: [{ id: "n1", key: "person.self", type: "person", label: "You", facts: [] }],
      edges: [{ id: "e1", relation: "instance_of", source: "n2", target: "g1", links_to_governance: true }],
      linked_governance_nodes: [{ id: "g1", key: "document.passport", entity_type: "document", label: "Passport" }],
    });
    expect(graph.nodes[0]?.scope).toBe("user");
    expect(graph.edges[0]?.scope).toBe("user");
    expect(graph.linkedNodes[0]?.scope).toBe("governance");
    expect(graph.linkedNodes[0]?.facts).toEqual({});
  });
});
