/**
 * Live DocumentService: uploads, what ADAPT read from them, and review.
 * The only code that knows the documents wire format (`/api/documents*`, `/api/review-tasks`).
 *
 * Privacy: files go straight from the file input to the API as multipart and are never
 * stored on the device. Content is shown from a short-lived signed URL the API returns
 * (`content_url`), which the service worker never caches (NetworkOnly for /api).
 */
import type {
  DocumentKind,
  DocumentStatus,
  ExtractedField,
  FieldCorrection,
  UserDocument,
} from "@/domain/documents";
import { api } from "@/lib/api/client";
import type { DocumentService } from "../types";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** Document routes, relative to `config.apiBaseUrl`. */
export const documentPaths = {
  list: "/documents",
  upload: "/documents/upload",
  document: (id: string) => `/documents/${encodeURIComponent(id)}`,
  review: (id: string) => `/documents/${encodeURIComponent(id)}/review`,
  process: (id: string) => `/documents/${encodeURIComponent(id)}/process`,
  reviewTasks: "/review-tasks",
  dismissTask: (id: string) => `/review-tasks/${encodeURIComponent(id)}/dismiss`,
} as const;

const STATUSES: ReadonlySet<string> = new Set([
  "uploaded",
  "processing",
  "extracted",
  "needs_review",
  "confirmed",
  "failed",
]);

/** Human-readable value of a field: the server's display form, else the raw value. */
export function fieldDisplayValue(raw: Raw): string | null {
  if (typeof raw.value_display === "string") return raw.value_display;
  if (raw.value === null || raw.value === undefined) return null;
  return typeof raw.value === "string" ? raw.value : JSON.stringify(raw.value);
}

export function toField(raw: Raw): ExtractedField {
  return {
    name: raw.name,
    label: raw.label ?? raw.name,
    value: fieldDisplayValue(raw),
    confidence: typeof raw.confidence === "number" ? raw.confidence : 0,
    needsReview: raw.needs_review === true,
  };
}

export function toDocument(raw: Raw): UserDocument {
  const status = (STATUSES.has(raw.status) ? raw.status : "failed") as DocumentStatus;
  const fields: Raw[] | undefined = raw.fields;
  return {
    id: raw.id,
    kind: raw.kind as DocumentKind,
    filename: raw.filename,
    contentType: raw.content_type,
    sizeBytes: raw.size_bytes,
    status,
    // The list endpoint returns metadata only; fields come with `get(id)`.
    extraction: fields
      ? {
          fields: fields.map(toField),
          warnings: [...(raw.warnings ?? []), ...reviewMessages(raw)],
          extractedAt: raw.processed_at ?? raw.created_at,
        }
      : null,
    usedFor: [],
    contentUrl: typeof raw.content_url === "string" ? raw.content_url : null,
    createdAt: raw.created_at,
    extractionRunId: raw.extraction_run_id ?? null,
    extractionMethod: raw.extraction_method ?? null,
    mrzVerified: typeof raw.mrz_verified === "boolean" ? raw.mrz_verified : null,
  };
}

/** Document-level review tasks (e.g. "couldn't read this automatically") as warnings. */
function reviewMessages(raw: Raw): string[] {
  return ((raw.review_tasks ?? []) as Raw[]).filter((t) => !t.fact).map((t) => String(t.message));
}

/** Correction values are sent as typed: dates, countries and money are normalised server-side. */
export function toCorrections(corrections: FieldCorrection[]): Raw[] {
  return corrections.map((c) => ({ name: c.name, value: c.value === "" ? null : c.value }));
}

export const liveDocuments: DocumentService = {
  async list(signal) {
    return ((await api.get<Raw[]>(documentPaths.list, { signal })) ?? []).map(toDocument);
  },
  async get(id, signal) {
    return toDocument(await api.get<Raw>(documentPaths.document(id), { signal }));
  },
  async upload(file, kind) {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("kind", kind);
    return toDocument(await api.post<Raw>(documentPaths.upload, form));
  },
  async review(id, corrections) {
    const body = { corrections: toCorrections(corrections), confirm: true };
    return toDocument(await api.post<Raw>(documentPaths.review(id), body));
  },
  async remove(id) {
    await api.delete<void>(documentPaths.document(id));
  },
};
