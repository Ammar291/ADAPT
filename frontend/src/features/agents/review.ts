import { tr } from "@/i18n";
/**
 * Pure helpers for answering a paused run's review (document corrections and submission
 * confirmations). Approvals are decided one by one through the approvals API instead.
 */
import type { DocumentCorrectionItem, ReviewAnswer, SubmissionConfirmationItem, SubmissionOutcome } from "@/domain/documents";

/** Edited values per document, per field name. */
export type CorrectionEdits = Record<string, Record<string, string>>;

/** Only fields whose value actually changed become corrections; every document is confirmed. */
export function buildCorrectionAnswer(items: DocumentCorrectionItem[], edits: CorrectionEdits): Extract<ReviewAnswer, { gate: "document_correction" }> {
  return {
    gate: "document_correction",
    documents: items.map((item) => {
      const changed = edits[item.documentId] ?? {};
      const corrections = item.fields
        .filter((field) => field.name in changed && (changed[field.name] ?? "").trim() !== (field.value ?? ""))
        .map((field) => {
          const value = (changed[field.name] ?? "").trim();
          return { name: field.name, value: value === "" ? null : value };
        });
      return { documentId: item.documentId, corrections, confirm: true };
    }),
  };
}

export interface ConfirmationDraft {
  outcome: SubmissionOutcome | null;
  reference: string;
  note: string;
}

export const OUTCOME_LABEL: Record<SubmissionOutcome, string> = {
  submitted: tr("copy.i_submitted_it_eeee4d3", { lng: "en" }),
  completed: tr("copy.i_received_a_completion_notice_dc9519f", { lng: "en" }),
  not_yet: tr("copy.not_yet_8de95fd", { lng: "en" }),
  could_not_complete: tr("copy.i_couldn_t_finish_it_f894fe6", { lng: "en" }),
};

/** Field-level problems, keyed by action id. Empty when the answer can be sent. */
export function confirmationErrors(items: SubmissionConfirmationItem[], drafts: Record<string, ConfirmationDraft>): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const item of items) {
    const draft = drafts[item.actionId];
    if (!draft?.outcome) errors[item.actionId] = "Choose what happened.";
    else if (draft.outcome === "completed" && !draft.reference.trim()) errors[item.actionId] = "Add the reference number from the official confirmation.";
  }
  return errors;
}

export function buildConfirmationAnswer(
  items: SubmissionConfirmationItem[],
  drafts: Record<string, ConfirmationDraft>,
): Extract<ReviewAnswer, { gate: "submission_confirmation" }> {
  return {
    gate: "submission_confirmation",
    confirmations: items.map((item) => {
      const draft = drafts[item.actionId]!;
      return {
        actionId: item.actionId,
        outcome: draft.outcome!,
        reference: draft.reference.trim() || null,
        note: draft.note.trim() || null,
      };
    }),
  };
}
