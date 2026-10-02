import { describe, expect, it } from "vitest";
import type { DocumentCorrectionItem, SubmissionConfirmationItem } from "@/domain/documents";
import { buildConfirmationAnswer, buildCorrectionAnswer, confirmationErrors } from "./review";

const doc: DocumentCorrectionItem = {
  documentId: "d1",
  kind: "passport",
  holder: "You",
  fields: [
    { name: "surname", label: "Surname", value: "Haddad", confidence: 0.98, needsReview: false },
    { name: "expiry", label: "Expiry date", value: "2031-02-01", confidence: 0.42, needsReview: true },
  ],
};

describe("buildCorrectionAnswer", () => {
  it("sends only fields that changed, and confirms every document", () => {
    const answer = buildCorrectionAnswer([doc], { d1: { surname: "Haddad", expiry: " 2031-02-10 " } });
    expect(answer).toEqual({
      gate: "document_correction",
      documents: [{ documentId: "d1", corrections: [{ name: "expiry", value: "2031-02-10" }], confirm: true }],
    });
  });

  it("clears a value when the field is emptied", () => {
    const answer = buildCorrectionAnswer([doc], { d1: { surname: "" } });
    expect(answer.documents[0]!.corrections).toEqual([{ name: "surname", value: null }]);
  });

  it("confirms untouched documents as they are", () => {
    expect(buildCorrectionAnswer([doc], {}).documents[0]).toEqual({ documentId: "d1", corrections: [], confirm: true });
  });
});

describe("submission confirmations", () => {
  const items: SubmissionConfirmationItem[] = [
    { actionId: "a1", kind: "official_handoff", title: "Trade name", officialUrl: null, simulationLabel: null },
    { actionId: "a2", kind: "appointment", title: "Medical test", officialUrl: null, simulationLabel: "DEMO / SIMULATED" },
  ];

  it("requires an outcome for every action, and a reference when complete", () => {
    const errors = confirmationErrors(items, { a1: { outcome: "completed", reference: " ", note: "" } });
    expect(Object.keys(errors).sort()).toEqual(["a1", "a2"]);
    expect(errors.a1).toMatch(/reference/);
  });

  it("builds the answer once valid", () => {
    const drafts = {
      a1: { outcome: "completed" as const, reference: " TN-123 ", note: "" },
      a2: { outcome: "not_yet" as const, reference: "", note: "Next week" },
    };
    expect(confirmationErrors(items, drafts)).toEqual({});
    expect(buildConfirmationAnswer(items, drafts).confirmations).toEqual([
      { actionId: "a1", outcome: "completed", reference: "TN-123", note: null },
      { actionId: "a2", outcome: "not_yet", reference: null, note: "Next week" },
    ]);
  });
});
