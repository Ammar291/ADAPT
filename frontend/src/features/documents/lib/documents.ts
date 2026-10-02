import { tr } from "@/i18n";
/**
 * Pure helpers for the Documents screen: upload validation, the processing pipeline,
 * confidence wording, masking of sensitive values and review corrections.
 */
import type { ActionStatus } from "@/domain/common";
import type { DocumentKind, DocumentStatus, ExtractedField, FieldCorrection, GeneratedDocument, GeneratedDocumentStatus } from "@/domain/documents";

// --- upload validation ------------------------------------------------------------------------

export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** File picker `accept` values. The camera input only takes images. */
export const UPLOAD_ACCEPT = tr("copy.image_application_pdf_b6fbf83", { lng: "en" });
export const CAMERA_ACCEPT = "image/*";

const IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "heic", "heif", "gif", "tif", "tiff", "bmp"];

export type UploadCheck = { ok: true } | { ok: false; message: string };

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** True for a PDF or any image. Some phones send HEIC photos with an empty MIME type. */
export function isAcceptedType(file: { name: string; type: string }): boolean {
  const type = file.type.toLowerCase();
  if (type === "application/pdf" || type.startsWith("image/")) return true;
  if (type && type !== "application/octet-stream") return false;
  const ext = extensionOf(file.name);
  return ext === "pdf" || IMAGE_EXTENSIONS.includes(ext);
}

/** Checks a picked file before it is sent. Messages say what happened and how to fix it. */
export function validateUpload(file: { name: string; type: string; size: number }): UploadCheck {
  if (!isAcceptedType(file)) {
    return { ok: false, message: tr("copy.this_file_type_isn_t_supported_upload_a_photo_jp_cd21144") };
  }
  if (file.size === 0) {
    return { ok: false, message: tr("copy.this_file_is_empty_choose_the_file_again_or_take_39138d8") };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return { ok: false, message: tr("copy.this_file_is_over_20_mb_take_a_new_photo_or_expo_5847088") };
  }
  return { ok: true };
}

export function isPdf(contentType: string, filename = ""): boolean {
  return contentType.toLowerCase() === "application/pdf" || extensionOf(filename) === "pdf";
}

export function isImage(contentType: string): boolean {
  return contentType.toLowerCase().startsWith("image/");
}

/** A document kind from a deep link (`?upload=passport`), or null when it isn't one. */
export function parseDocumentKind(value: string | null, kinds: readonly DocumentKind[]): DocumentKind | null {
  if (!value) return null;
  return (kinds as readonly string[]).includes(value) ? (value as DocumentKind) : null;
}

// --- processing pipeline ----------------------------------------------------------------------

export type StepState = "done" | "current" | "todo" | "failed";

export interface PipelineStep {
  key: "uploaded" | "reading" | "review" | "confirmed";
  label: string;
  state: StepState;
}

export type PipelineTone = "working" | "attention" | "ready" | "done" | "failed";

export interface Pipeline {
  steps: PipelineStep[];
  /** Short status in plain words. */
  label: string;
  /** One sentence on what happens next. */
  detail: string;
  tone: PipelineTone;
  /** Still moving on its own (no user action needed yet). */
  busy: boolean;
}

const STEP_LABELS: Record<PipelineStep["key"], string> = {
  uploaded: tr("copy.uploaded_80c4948", { lng: "en" }),
  reading: tr("copy.read_852b438", { lng: "en" }),
  review: tr("copy.checked_b2bc0c0", { lng: "en" }),
  confirmed: tr("copy.confirmed_8cc7acb", { lng: "en" }),
};

function steps(states: [StepState, StepState, StepState, StepState]): PipelineStep[] {
  return (["uploaded", "reading", "review", "confirmed"] as const).map((key, i) => ({ key, label: STEP_LABELS[key], state: states[i]! }));
}

/** Where a document is in uploaded → read → checked → confirmed. */
export function pipelineOf(status: DocumentStatus, reviewCount = 0): Pipeline {
  switch (status) {
    case "uploaded":
      return {
        steps: steps(["done", "current", "todo", "todo"]),
        label: tr("copy.waiting_to_be_read_b78a4e9"),
        detail: tr("copy.adapt_will_start_reading_it_in_a_moment_ba4a20c"),
        tone: "working",
        busy: true,
      };
    case "processing":
      return {
        steps: steps(["done", "current", "todo", "todo"]),
        label: tr("copy.reading_cffa2af"),
        detail: tr("copy.adapt_is_reading_the_details_this_usually_takes__c3059bf"),
        tone: "working",
        busy: true,
      };
    case "needs_review":
      return {
        steps: steps(["done", "done", "current", "todo"]),
        label: reviewCount === 1 ? tr("copy.check_1_detail_8bfcdeb") : reviewCount > 1 ? `Check ${reviewCount} details` : tr("copy.check_the_details_f542549"),
        detail: tr("copy.adapt_wasn_t_sure_about_some_details_check_them__0149d6f"),
        tone: "attention",
        busy: false,
      };
    case "extracted":
      return {
        steps: steps(["done", "done", "current", "todo"]),
        label: tr("copy.ready_to_confirm_1642323"),
        detail: tr("copy.everything_was_read_clearly_confirm_the_details__5c2acf8"),
        tone: "ready",
        busy: false,
      };
    case "confirmed":
      return {
        steps: steps(["done", "done", "done", "done"]),
        label: tr("copy.confirmed_8cc7acb"),
        detail: tr("copy.you_confirmed_these_details_adapt_uses_them_in_y_bcdf427"),
        tone: "done",
        busy: false,
      };
    case "failed":
      return {
        steps: steps(["done", "failed", "todo", "todo"]),
        label: tr("copy.couldn_t_read_it_00f16e8"),
        detail: tr("copy.upload_a_sharper_photo_or_a_pdf_with_the_whole_p_91f8946"),
        tone: "failed",
        busy: false,
      };
  }
}

// --- extracted fields -------------------------------------------------------------------------

export type ConfidenceLevel = "high" | "medium" | "low";

export const CONFIDENCE_TEXT: Record<ConfidenceLevel, string> = {
  high: tr("copy.high_confidence_6c2943a", { lng: "en" }),
  medium: tr("copy.medium_confidence_156b5ba", { lng: "en" }),
  low: tr("copy.low_confidence_99d4cea", { lng: "en" }),
};

export function confidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.9) return "high";
  if (confidence >= 0.7) return "medium";
  return "low";
}

const SENSITIVE_NAME =
  /(passport|document|certificate|licen[cs]e|permit|visa|emirates_id|identity|id_card|national_id|account|iban|card|registration|file|unified)_?(number|no|num)$|^(id_number|iban|account_number|document_number|mrz|mrz_line_\d)$/i;

/** Document and account numbers are hidden until the user asks to see them. */
export function isSensitiveField(field: Pick<ExtractedField, "name" | "label">): boolean {
  if (SENSITIVE_NAME.test(field.name)) return true;
  return /\b(passport|document|certificate|id|licen[cs]e|account|card)\s+(number|no\.?)\b/i.test(field.label);
}

/** "UT4821937" → "•••••1937". Short values are hidden entirely. */
export function maskValue(value: string | null, visible = 4): string {
  if (!value) return "";
  const compact = value.trim();
  if (compact.length <= visible + 1) return "•".repeat(Math.max(4, compact.length));
  return "•".repeat(Math.min(6, compact.length - visible)) + compact.slice(-visible);
}

/** Only the fields the user changed, with blank values sent as null. */
export function diffCorrections(fields: ExtractedField[], values: Record<string, string>): FieldCorrection[] {
  const out: FieldCorrection[] = [];
  for (const field of fields) {
    if (!(field.name in values)) continue;
    const next = values[field.name]!.trim();
    const before = (field.value ?? "").trim();
    if (next === before) continue;
    out.push({ name: field.name, value: next === "" ? null : next });
  }
  return out;
}

export function reviewCount(fields: ExtractedField[] | undefined | null): number {
  return fields?.filter((f) => f.needsReview).length ?? 0;
}

// --- journey links ------------------------------------------------------------------------------

/** "residency.entry_permit" → "Entry permit" when the journey isn't loaded. */
export function humanizeNodeKey(key: string): string {
  const last = key.split(".").pop() ?? key;
  const words = last.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

// --- drafts ---------------------------------------------------------------------------------------

export const DRAFT_STATUS_TEXT: Record<GeneratedDocumentStatus, string> = {
  draft: tr("copy.draft_23d33e2", { lng: "en" }),
  approved: tr("copy.approved_41b81eb", { lng: "en" }),
  discarded: tr("copy.discarded_7ecfbf0", { lng: "en" }),
};

const DRAFT_ORDER: Record<GeneratedDocumentStatus, number> = { draft: 0, approved: 1, discarded: 2 };

/** Drafts waiting for review first, then approved, then discarded; newest first within each. */
export function sortDrafts(drafts: GeneratedDocument[]): GeneratedDocument[] {
  return [...drafts].sort((a, b) => DRAFT_ORDER[a.status] - DRAFT_ORDER[b.status] || b.updatedAt.localeCompare(a.updatedAt));
}

// --- actions --------------------------------------------------------------------------------------

/** Action status in plain words. Never implies a submission that didn't happen. */
export const ACTION_STATUS_TEXT: Record<ActionStatus, string> = {
  draft: tr("copy.draft_23d33e2", { lng: "en" }),
  prepared: tr("copy.prepared_d8b21a6", { lng: "en" }),
  awaiting_approval: tr("copy.approval_required_b8d012c", { lng: "en" }),
  approved: tr("copy.approved_41b81eb", { lng: "en" }),
  submitted: tr("copy.submitted_as_confirmed_0754b6b", { lng: "en" }),
  completed: tr("copy.completed_as_confirmed_99c9218", { lng: "en" }),
  blocked: tr("copy.blocked_99613c7", { lng: "en" }),
  failed: tr("copy.didn_t_go_through_b379615", { lng: "en" }),
  handoff_required: tr("copy.official_handoff_f59d25d", { lng: "en" }),
  rejected: tr("copy.declined_ff59b80", { lng: "en" }),
  cancelled: tr("copy.cancelled_a1bf92e", { lng: "en" }),
};

export type ActionTone = "neutral" | "primary" | "ink" | "danger";

export function actionStatusTone(status: ActionStatus): ActionTone {
  switch (status) {
    case "completed":
    case "submitted":
    case "approved":
      return "primary";
    case "handoff_required":
    case "awaiting_approval":
      return "ink";
    case "blocked":
    case "failed":
      return "danger";
    default:
      return "neutral";
  }
}
