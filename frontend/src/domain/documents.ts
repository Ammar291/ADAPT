import type { ActionKind, ActionStatus, Evidence } from "./common";

export type DocumentKind =
  | "passport"
  | "marriage_certificate"
  | "employment_letter"
  | "business_document"
  | "tenancy_document"
  | "identity_document"
  | "miscellaneous";

export const DOCUMENT_KIND_LABEL: Record<DocumentKind, string> = {
  passport: "Passport",
  marriage_certificate: "Marriage certificate",
  employment_letter: "Employment letter",
  business_document: "Business document",
  tenancy_document: "Tenancy document",
  identity_document: "ID document or photo",
  miscellaneous: "Other document",
};

/** `extracted` = read with nothing to review; `needs_review` = some fields need a look. */
export type DocumentStatus = "uploaded" | "processing" | "extracted" | "needs_review" | "confirmed" | "failed";

export interface ExtractedField {
  name: string;
  label: string;
  value: string | null;
  /** 0–1. Low-confidence fields are highlighted for review. */
  confidence: number;
  needsReview: boolean;
}

export interface DocumentExtraction {
  fields: ExtractedField[];
  warnings: string[];
  extractedAt: string;
}

/**
 * Metadata only. Document bytes are streamed from a no-store endpoint (or, in mock mode,
 * held as an in-memory object URL) and are never cached or persisted on the device.
 */
export interface UserDocument {
  id: string;
  kind: DocumentKind;
  filename: string;
  contentType: string;
  sizeBytes: number;
  status: DocumentStatus;
  extraction: DocumentExtraction | null;
  /** Journey nodes this document satisfies. */
  usedFor: string[];
  /**
   * Where to display the bytes: a short-lived signed API URL (live) or an in-memory object
   * URL (mock). Never cached by the service worker; null when there is nothing to show.
   */
  contentUrl: string | null;
  createdAt: string;
  /** The reading run (classify, read, check, organise, update the twin), when there is one. */
  extractionRunId?: string | null;
  /** How it was read, e.g. "local:pdf-text" (PDF text layer, offline) or an OCR/vision model. */
  extractionMethod?: string | null;
  /** Passports: the machine-readable lines passed their check digits and confirmed the details. */
  mrzVerified?: boolean | null;
}

export interface FieldCorrection {
  name: string;
  value: string | null;
}

export type GeneratedDocumentKind =
  | "cover_letter"
  | "email"
  | "checklist"
  | "form_prefill"
  | "business_summary"
  | "appointment_brief"
  | "plan";

export const GENERATED_KIND_LABEL: Record<GeneratedDocumentKind, string> = {
  cover_letter: "Cover letter",
  email: "Email",
  checklist: "Checklist",
  form_prefill: "Form details",
  business_summary: "Business summary",
  appointment_brief: "Appointment brief",
  plan: "Your Abu Dhabi plan",
};

export type GeneratedDocumentStatus = "draft" | "approved" | "discarded";

/** A document ADAPT drafted. Always reviewed by the user before use. */
export interface GeneratedDocument {
  id: string;
  kind: GeneratedDocumentKind;
  title: string;
  bodyMarkdown: string;
  status: GeneratedDocumentStatus;
  journeyNodeKey: string | null;
  evidence: Evidence;
  createdAt: string;
  updatedAt: string;
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";

/** What kind of human-in-the-loop checkpoint this is. */
export type ApprovalGate = "action_approval" | "document_correction" | "submission_confirmation";

/** A consequential action paused until the user decides (gate `action_approval`). */
export interface Approval {
  id: string;
  /** The action this approval authorises. */
  actionId: string | null;
  runId: string | null;
  gate: ApprovalGate;
  actionKind: ActionKind;
  title: string;
  summary: string;
  consequences: string[];
  /** Exactly what will be sent or prefilled. */
  payloadPreview: Record<string, string>;
  requiresUserAuthentication: boolean;
  reversible: boolean;
  officialUrl: string | null;
  /** Shown as a visible label (e.g. "DEMO / SIMULATED") when the adapter is simulated. */
  simulationLabel: string | null;
  status: ApprovalStatus;
  journeyNodeKey: string | null;
  createdAt: string;
  decidedAt: string | null;
}

export interface ActionRecord {
  id: string;
  kind: ActionKind;
  status: ActionStatus;
  title: string;
  message: string;
  handoffUrl: string | null;
  /** Only present when an external system returned one, or the user reported one. */
  externalReference: string | null;
  confirmationSource: "adapter" | "user_reported" | null;
  isSimulated: boolean;
  simulationLabel: string | null;
  journeyNodeKey: string | null;
  createdAt: string;
}

export interface DocumentCorrectionItem {
  documentId: string;
  kind: DocumentKind;
  /** Whose document it is, e.g. "You" or "Your spouse". */
  holder: string | null;
  fields: ExtractedField[];
}

export interface SubmissionConfirmationItem {
  actionId: string;
  kind: ActionKind;
  title: string;
  officialUrl: string | null;
  simulationLabel: string | null;
}

export type SubmissionOutcome = "submitted" | "completed" | "not_yet" | "could_not_complete";

/** A paused run's human checkpoint, rendered as the Review step. */
export type Review =
  | { gate: "action_approval"; runId: string; reviewId: string; items: Approval[] }
  | { gate: "document_correction"; runId: string; reviewId: string; items: DocumentCorrectionItem[] }
  | { gate: "submission_confirmation"; runId: string; reviewId: string; items: SubmissionConfirmationItem[] };

export type ReviewAnswer =
  | { gate: "document_correction"; documents: { documentId: string; corrections: FieldCorrection[]; confirm: boolean }[] }
  | {
      gate: "submission_confirmation";
      confirmations: { actionId: string; outcome: SubmissionOutcome; reference: string | null; note: string | null }[];
    };
