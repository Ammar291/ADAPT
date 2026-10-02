import { tr, localize, useLocale } from "@/i18n";
import { Camera, FileUp, Lock, Upload } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRef, useState, type DragEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Sheet } from "@/components/ui/Sheet";
import { EmptyState, ErrorState, Skeleton, SkeletonText } from "@/components/ui/States";
import { DOCUMENT_KIND_LABEL, type DocumentKind, type UserDocument } from "@/domain/documents";
import { useDocuments } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { useIsTouch, useNodeTitles } from "../hooks";
import { DocumentDetail } from "./DocumentDetail";
import { DocumentList } from "./DocumentList";

export interface UploadRequest {
  kind?: DocumentKind | null;
  file?: File | null;
  camera?: boolean;
}

function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
}

function summary(documents: UserDocument[]): string {
  const reading = documents.filter((d) => d.status === "uploaded" || d.status === "processing").length;
  const toConfirm = documents.filter((d) => d.status === "needs_review" || d.status === "extracted").length;
  const parts = [reading ? `${reading} being read` : null, toConfirm ? `${toConfirm} to confirm` : null].filter(Boolean);
  return parts.join(", ");
}

function FirstUpload({ onUpload }: { onUpload: (request: UploadRequest) => void }) {
  useLocale();
  const touch = useIsTouch();
  return (
    <EmptyState
      icon={<FileUp className="size-5" aria-hidden />}
      title={tr("copy.start_with_your_passport_efc6dad")}
      description={
        <>
          <p>{tr("copy.most_steps_in_your_plan_need_it_then_add_a_passp_939564d")}</p>
          <p className="mt-2">{tr("copy.adapt_reads_each_one_and_shows_you_what_it_found_003ce54")}</p>
        </>
      }
      action={
        <div className="flex flex-col gap-4">
          <div className="grid gap-2 sm:flex sm:flex-wrap">
            {touch && (
              <Button icon={<Camera className="size-4" aria-hidden />} onClick={() => onUpload({ kind: "passport", camera: true })}>
                {tr("copy.scan_passport_with_camera_a5334a4")}</Button>
            )}
            <Button variant={touch ? "secondary" : "primary"} icon={<Upload className="size-4" aria-hidden />} onClick={() => onUpload({ kind: "passport" })}>
              {tr("copy.upload_passport_c489a00")}</Button>
            <Button variant="secondary" onClick={() => onUpload({ kind: "identity_document" })}>
              {tr("copy.upload_photo_69abef7")}</Button>
            <Button variant="secondary" onClick={() => onUpload({ kind: "marriage_certificate" })}>
              {tr("copy.upload_marriage_certificate_0339c7b")}</Button>
          </div>
          <p className="flex items-start gap-2 text-xs text-muted">
            <Lock className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
            {tr("copy.encrypted_never_saved_on_this_device_delete_any__f172609")}</p>
        </div>
      }
    />
  );
}

export function DocumentsTab({
  selectedId,
  onSelect,
  onUpload,
  wide,
}: {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onUpload: (request: UploadRequest) => void;
  /** The page is wide enough for the list beside the detail; otherwise details open in a sheet. */
  wide: boolean;
}) {
  useLocale();
  const isDesktop = wide;
  const query = useDocuments();
  const nodeTitle = useNodeTitles();
  const reduce = useReducedMotion();
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const lastSheetDoc = useRef<UserDocument | null>(null);

  if (query.isPending) {
    return (
      <div role="status" aria-label={tr("copy.loading_documents_9f1e0ce")} className="grid gap-6 @4xl/main:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex gap-3">
              <Skeleton className="size-10" />
              <div className="flex-1">
                <SkeletonText lines={2} />
              </div>
            </div>
          ))}
        </div>
        <div className="hidden rounded-xl border border-line bg-surface p-6 @4xl/main:block">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="mt-6 h-64 w-full" />
        </div>
      </div>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const documents = query.data;
  if (!documents.length) return <FirstUpload onUpload={onUpload} />;

  const explicit = documents.find((d) => d.id === selectedId) ?? null;
  const selected = explicit ?? (isDesktop ? documents[0]! : null);
  if (!isDesktop && explicit) lastSheetDoc.current = explicit;
  const sheetDoc = lastSheetDoc.current ? (documents.find((d) => d.id === lastSheetDoc.current!.id) ?? lastSheetDoc.current) : null;
  const status = summary(documents);

  const dropHandlers = isDesktop
    ? {
        onDragEnter: (event: DragEvent) => {
          if (!hasFiles(event)) return;
          depth.current += 1;
          setDragging(true);
        },
        onDragLeave: () => {
          depth.current = Math.max(0, depth.current - 1);
          if (depth.current === 0) setDragging(false);
        },
        onDragOver: (event: DragEvent) => {
          if (hasFiles(event)) event.preventDefault();
        },
        onDrop: (event: DragEvent) => {
          if (!hasFiles(event)) return;
          event.preventDefault();
          depth.current = 0;
          setDragging(false);
          const file = event.dataTransfer.files[0];
          if (file) onUpload({ file });
        },
      }
    : {};

  return (
    <div className="relative" {...dropHandlers}>
      <div className="grid items-start gap-6 @4xl/main:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <Card tone="raised" className="overflow-hidden">
          <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
            <h2 className="font-sans text-sm font-medium">{documents.length === 1 ? tr("copy.1_document_8e3e1df") : tr("copy.v0_documents_18b0244", { v0: documents.length })}</h2>
            {status && (
              <span className="text-xs text-muted" aria-live="polite">
                {localize(status)}
              </span>
            )}
          </div>
          <DocumentList documents={documents} selectedId={selected?.id ?? null} onSelect={onSelect} nodeTitle={nodeTitle} opensDialog={!isDesktop} />
          {isDesktop && (
            <div className="border-t border-line px-5 py-3">
              <p className="flex items-center gap-2 text-2xs text-subtle">
                <Upload className="size-3.5" aria-hidden />
                {tr("copy.drag_a_photo_or_pdf_onto_this_page_to_upload_it_a3b64cb")}</p>
            </div>
          )}
        </Card>

        {isDesktop && selected && (
          <Card tone="strong" className="min-w-0 p-6 @6xl/main:p-8">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={selected.id}
                initial={reduce ? false : { opacity: 0, x: 8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={reduce ? undefined : { opacity: 0 }}
                transition={{ duration: 0.18, ease: [0.2, 0, 0, 1] }}
              >
                <DocumentDetail doc={selected} nodeTitle={nodeTitle} onDeleted={() => onSelect(null)} onReupload={(doc) => onUpload({ kind: doc.kind })} />
              </motion.div>
            </AnimatePresence>
          </Card>
        )}
      </div>

      {!isDesktop && sheetDoc && (
        <Sheet open={Boolean(explicit)} onClose={() => onSelect(null)} title={localize(DOCUMENT_KIND_LABEL[sheetDoc.kind])} description={sheetDoc.filename} tall>
          <DocumentDetail
            key={sheetDoc.id}
            doc={sheetDoc}
            nodeTitle={nodeTitle}
            showHeader={false}
            onDeleted={() => {
              lastSheetDoc.current = null;
              onSelect(null);
            }}
            onReupload={(doc) => {
              onSelect(null);
              onUpload({ kind: doc.kind });
            }}
          />
        </Sheet>
      )}

      {dragging && (
        <div
          className={cn(
            "pointer-events-none absolute -inset-3 z-20 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-primary-tint/85",
          )}
          aria-hidden
        >
          <p className="flex items-center gap-2 rounded-lg bg-surface px-4 py-3 font-medium text-primary-strong shadow-raised">
            <Upload className="size-5" />
            {tr("copy.drop_to_upload_you_ll_say_what_it_is_next_33ce01f")}</p>
        </div>
      )}
    </div>
  );
}
