/**
 * Live adapter for documents ADAPT drafted (`/documents/generated`). Editing saves the text and
 * makes it a draft again (it also restores a discarded draft); an approved document is final
 * (409 `generated_document_already_approved`).
 */
import type { EvidenceKind } from "@/domain/common";
import type { GeneratedDocument, GeneratedDocumentKind } from "@/domain/documents";
import { api } from "@/lib/api/client";
import type { GeneratedDocumentService } from "../types";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const generatedPaths = {
  list: "/documents/generated",
  one: (id: string) => `/documents/generated/${encodeURIComponent(id)}`,
  approve: (id: string) => `/documents/generated/${encodeURIComponent(id)}/approve`,
  discard: (id: string) => `/documents/generated/${encodeURIComponent(id)}/discard`,
} as const;

export function toGeneratedDocument(raw: Raw): GeneratedDocument {
  const provenance = (raw.provenance ?? {}) as Raw;
  const details = (raw.details ?? {}) as Raw;
  return {
    id: raw.id,
    kind: raw.kind as GeneratedDocumentKind,
    title: raw.title,
    bodyMarkdown: raw.body_markdown ?? "",
    status: raw.status,
    journeyNodeKey: details.task_key ?? details.node_key ?? null,
    evidence: {
      kind: (provenance.kind ?? "ai_recommendation") as EvidenceKind,
      citations: ((provenance.citations ?? []) as Raw[]).map((c) => ({
        title: c.source_title ?? c.title ?? "",
        url: c.source_url ?? c.url ?? "",
        authority: c.authority ?? null,
        retrievedAt: c.retrieved_at ?? null,
        section: c.section ?? null,
        quote: c.quote ?? null,
      })),
      confidence: provenance.confidence ?? null,
      note: provenance.note ?? null,
    },
    createdAt: raw.created_at,
    updatedAt: raw.updated_at ?? raw.created_at,
  };
}

const unwrap = (raw: Raw): Raw => (raw.document ?? raw) as Raw;

export const liveGenerated: GeneratedDocumentService = {
  async list(signal) {
    const raw = await api.get<Raw[] | Raw>(generatedPaths.list, { signal });
    const items = Array.isArray(raw) ? raw : ((raw.items ?? raw.documents ?? []) as Raw[]);
    return items.map(toGeneratedDocument);
  },
  async approve(id) {
    return toGeneratedDocument(unwrap(await api.post<Raw>(generatedPaths.approve(id))));
  },
  async discard(id) {
    return toGeneratedDocument(unwrap(await api.post<Raw>(generatedPaths.discard(id))));
  },
  async update(id, bodyMarkdown) {
    return toGeneratedDocument(unwrap(await api.patch<Raw>(generatedPaths.one(id), { body_markdown: bodyMarkdown })));
  },
};
