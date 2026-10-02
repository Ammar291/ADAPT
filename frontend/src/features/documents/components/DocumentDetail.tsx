import { tr, localize, useLocale } from "@/i18n";
import { Eye, EyeOff, ExternalLink, Lock, PenLine, RotateCcw, Route, Trash2, TriangleAlert, Upload } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { toast } from "@/components/ui/Toast";
import { DOCUMENT_KIND_LABEL, type DocumentExtraction, type ExtractedField, type UserDocument } from "@/domain/documents";
import { describeError } from "@/lib/api/errors";
import { useDeleteDocument, useReviewDocument } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatBytes, formatDate, relativeTime } from "@/lib/format";
import { useDocument, useIsTouch } from "../hooks";
import {
  CONFIDENCE_TEXT,
  confidenceLevel,
  diffCorrections,
  isImage,
  isPdf,
  isSensitiveField,
  maskValue,
  reviewCount,
  type ConfidenceLevel,
} from "../lib/documents";
import { KIND_ICON, PipelineSteps } from "./Pipeline";

// --- preview ------------------------------------------------------------------------------------

function OpenInNewTab({ url, className }: { url: string; className?: string }) {
  useLocale();
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("inline-flex items-center gap-1.5 text-sm font-medium text-primary-strong underline underline-offset-4", className)}
    >
      {tr("copy.open_in_new_tab_71bf47a")}<ExternalLink className="size-3.5" aria-hidden />
    </a>
  );
}

/** A quiet stand-in for documents with nothing to show (e.g. sample documents). */
function PreviewPlaceholder({ doc, note }: { doc: UserDocument; note: string }) {
  useLocale();
  const Icon = KIND_ICON[doc.kind];
  const landscape = doc.kind === "passport" || doc.kind === "identity_document";
  return (
    <div className="flex items-center justify-center rounded-lg bg-sunken p-5 sm:p-6">
      <div
        className={cn(
          "flex w-full flex-col justify-between rounded-md border border-line bg-surface p-4 shadow-card",
          landscape ? "aspect-[1.42] max-w-[320px]" : "aspect-[1/1.25] max-w-[240px]",
        )}
      >
        <div className="flex items-start gap-3">
          <span className={cn("flex shrink-0 items-center justify-center rounded bg-sunken text-subtle", landscape ? "h-14 w-11" : "size-9")} aria-hidden>
            <Icon className="size-5" />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1.5 pt-1" aria-hidden>
            <span className="h-1.5 w-3/4 rounded-full bg-sunken" />
            <span className="h-1.5 w-1/2 rounded-full bg-sunken" />
            <span className="h-1.5 w-2/3 rounded-full bg-sunken" />
          </div>
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium">{localize(DOCUMENT_KIND_LABEL[doc.kind])}</p>
          <p className="truncate text-2xs text-muted">{doc.filename}</p>
        </div>
      </div>
      <p className="sr-only">{localize(note)}</p>
    </div>
  );
}

export function DocumentPreview({ doc }: { doc: UserDocument }) {
  useLocale();
  const touch = useIsTouch();
  const [failed, setFailed] = useState(false);
  const url = doc.contentUrl;

  if (!url || failed) {
    return (
      <figure>
        <PreviewPlaceholder doc={doc} note="No preview for this file." />
        <figcaption className="mt-2 text-2xs text-subtle">
          {failed ? tr("copy.the_preview_couldn_t_load_the_details_adapt_read_34f4d24") : tr("copy.no_preview_for_this_file_the_details_adapt_read__cb5ae1e")}
        </figcaption>
      </figure>
    );
  }
  if (isImage(doc.contentType)) {
    return (
      <figure>
        <div className="flex items-center justify-center overflow-hidden rounded-lg bg-sunken">
          <img
            src={url}
            alt={localize(`${DOCUMENT_KIND_LABEL[doc.kind]}: ${doc.filename}`)}
            onError={() => setFailed(true)}
            className="max-h-[420px] w-full object-contain"
          />
        </div>
        <figcaption className="mt-2">
          <OpenInNewTab url={url} />
        </figcaption>
      </figure>
    );
  }
  if (isPdf(doc.contentType, doc.filename) && !touch) {
    return (
      <figure>
        <iframe src={url} title={localize(`${DOCUMENT_KIND_LABEL[doc.kind]}: ${doc.filename}`)} className="h-[440px] w-full rounded-lg border border-line bg-sunken" />
        <figcaption className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-subtle">
          <OpenInNewTab url={url} />
          {tr("copy.if_the_pdf_doesn_t_show_here_open_it_in_a_new_ta_5b2a24d")}</figcaption>
      </figure>
    );
  }
  return (
    <figure>
      <PreviewPlaceholder doc={doc} note="Open the file to see it." />
      <figcaption className="mt-2">
        <OpenInNewTab url={url} />
      </figcaption>
    </figure>
  );
}

// --- fields -------------------------------------------------------------------------------------

const METER: Record<ConfidenceLevel, number> = { high: 3, medium: 2, low: 1 };

function Confidence({ value }: { value: number }) {
  useLocale();
  const level = confidenceLevel(value);
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-2xs text-muted">
      <span className="flex items-end gap-0.5" aria-hidden>
        {[1, 2, 3].map((bar) => (
          <span
            key={bar}
            className={cn("w-[3px] rounded-full", bar <= METER[level] ? (level === "low" ? "bg-ink" : "bg-primary") : "bg-line-strong")}
            style={{ height: 4 + bar * 3 }}
          />
        ))}
      </span>
      {localize(CONFIDENCE_TEXT[level])}
    </span>
  );
}

function MaskToggle({ shown, label, onToggle, compact = false }: { shown: boolean; label: string; onToggle: () => void; compact?: boolean }) {
  useLocale();
  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={onToggle}
      aria-pressed={shown}
      aria-label={localize(`${shown ? tr("copy.hide_34d8b60") : tr("copy.show_d97d1ee")} ${label.toLowerCase()}`)}
      icon={shown ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
      className={cn("shrink-0", compact ? "-my-1" : "h-10")}
    >
      {shown ? tr("copy.hide_34d8b60") : tr("copy.show_d97d1ee")}
    </Button>
  );
}

function FieldRow({
  field,
  value,
  editing,
  shown,
  onChange,
  onToggleShown,
}: {
  field: ExtractedField;
  value: string;
  editing: boolean;
  shown: boolean;
  onChange: (value: string) => void;
  onToggleShown: () => void;
}) {
  useLocale();
  const id = `field-${field.name}`;
  const sensitive = isSensitiveField(field);
  const masked = sensitive && !shown;
  const flagged = field.needsReview && editing;
  const hintId = `${id}-hint`;

  return (
    <div className={cn(editing ? "py-3" : "py-2.5", flagged && "my-1 rounded-e-lg border-s-2 border-b-0 border-ink bg-muted-surface ps-3 pe-3")}>
      <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1", editing && "mb-1.5")}>
        <label htmlFor={editing && !masked ? id : undefined} className={editing ? "text-sm font-medium" : "text-xs text-muted"}>
          {localize(field.label)}
        </label>
        {flagged && <Badge tone="ink">{tr("copy.check_this_595cd6d")}</Badge>}
        <span className="ms-auto">
          <Confidence value={field.confidence} />
        </span>
      </div>
      {editing ? (
        <div className="flex items-center gap-2">
          {masked ? (
            <div
              className="flex h-10 min-w-0 flex-1 items-center rounded-md border border-line bg-sunken px-3 text-sm tracking-wider text-muted"
              aria-label={localize(tr("copy.v0_hidden_02863ab", { v0: field.label }))}
            >
              {localize(maskValue(value) || tr("copy.not_found_475c848"))}
            </div>
          ) : (
            <input
              id={id}
              value={value}
              onChange={(event) => onChange(event.target.value)}
              placeholder={field.value === null ? tr("copy.not_found_add_it_if_you_have_it_075642e") : undefined}
              aria-describedby={flagged ? hintId : undefined}
              autoComplete="off"
              spellCheck={false}
              className="h-10 w-full min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-subtle focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
            />
          )}
          {sensitive && <MaskToggle shown={shown} label={localize(field.label)} onToggle={onToggleShown} />}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <p className={cn("min-w-0 flex-1 text-sm font-medium break-words", !value && "font-normal text-subtle", masked && "tracking-wider")}>
            {masked ? maskValue(value) || tr("copy.not_found_475c848") : value || tr("copy.not_found_475c848")}
          </p>
          {sensitive && value && <MaskToggle compact shown={shown} label={localize(field.label)} onToggle={onToggleShown} />}
        </div>
      )}
      {flagged && (
        <p id={hintId} className="mt-1.5 text-xs text-muted">
          {field.value === null ? tr("copy.adapt_couldn_t_find_this_add_it_if_it_s_on_your__898f42b") : tr("copy.adapt_wasn_t_sure_about_this_compare_it_with_you_0f7954b")}
        </p>
      )}
    </div>
  );
}

function FieldsForm({ doc, extraction }: { doc: UserDocument; extraction: DocumentExtraction }) {
  useLocale();
  const review = useReviewDocument();
  const confirmed = doc.status === "confirmed";
  const [editing, setEditing] = useState(!confirmed);
  const initial = () => Object.fromEntries(extraction.fields.map((f) => [f.name, f.value ?? ""]));
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [shown, setShown] = useState<Set<string>>(() => new Set());
  const corrections = diffCorrections(extraction.fields, values);
  const toCheck = reviewCount(extraction.fields);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    review.mutate(
      { id: doc.id, corrections },
      {
        onSuccess: () => {
          toast({
            title: confirmed ? tr("copy.details_saved_693c1a8") : tr("copy.details_confirmed_59f184e"),
            description: tr("copy.adapt_will_use_your_v0_details_in_your_plan_10d15b7", { v0: DOCUMENT_KIND_LABEL[doc.kind].toLowerCase() }),
          });
        },
        onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail, tone: "error" }),
      },
    );
  };

  const toggle = (name: string) =>
    setShown((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <form onSubmit={submit} aria-labelledby={`fields-${doc.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`fields-${doc.id}`} className="text-base font-medium">
          {tr("copy.what_adapt_read_178619b")}</h3>
        {editing && toCheck > 0 && <span className="text-xs text-muted">{toCheck === 1 ? tr("copy.1_detail_to_check_9c047cf") : tr("copy.v0_details_to_check_625a378", { v0: toCheck })}</span>}
        {!editing && (
          <Button size="sm" variant="ghost" icon={<PenLine className="size-4" aria-hidden />} onClick={() => setEditing(true)}>
            {tr("copy.edit_details_4173a96")}</Button>
        )}
      </div>

      {extraction.warnings.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {extraction.warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-2.5 rounded-lg border border-danger/25 bg-danger-tint px-3 py-2.5 text-sm">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
              {localize(warning)}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2 divide-y divide-line">
        {extraction.fields.map((field) => (
          <FieldRow
            key={field.name}
            field={field}
            value={values[field.name] ?? ""}
            editing={editing}
            shown={shown.has(field.name)}
            onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
            onToggleShown={() => toggle(field.name)}
          />
        ))}
      </div>

      {editing && (
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line pt-4">
          <Button type="submit" loading={review.isPending}>
            {confirmed ? tr("copy.save_details_4706583") : tr("copy.confirm_details_07c14f9")}
          </Button>
          {corrections.length > 0 && (
            <Button variant="ghost" icon={<RotateCcw className="size-4" aria-hidden />} onClick={() => setValues(initial())}>
              {tr("copy.undo_changes_6f5e312")}</Button>
          )}
          {confirmed && corrections.length === 0 && (
            <Button variant="ghost" onClick={() => setEditing(false)}>
              {tr("copy.cancel_77dfd21")}</Button>
          )}
          <span className="text-xs text-muted" aria-live="polite">
            {corrections.length === 1 ? tr("copy.1_change_will_be_saved_9e11445") : corrections.length > 1 ? tr("copy.v0_changes_will_be_saved_ba34992", { v0: corrections.length }) : ""}
          </span>
        </div>
      )}
      <p className="mt-3 text-2xs text-subtle">{tr("copy.read_e755e58")}{localize(formatDate(extraction.extractedAt))}{tr("copy.confidence_shows_how_clearly_adapt_could_read_ea_09d2a9c")}</p>
    </form>
  );
}

function ReadingSkeleton() {
  useLocale();
  return (
    <div aria-hidden className="flex flex-col gap-4">
      <Skeleton className="h-4 w-32" />
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex flex-col gap-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-10 w-full" />
        </div>
      ))}
    </div>
  );
}

// --- detail -------------------------------------------------------------------------------------

export function DocumentDetail({
  doc: listDoc,
  nodeTitle,
  showHeader = true,
  onDeleted,
  onReupload,
}: {
  doc: UserDocument;
  nodeTitle: (key: string) => string;
  /** Off inside a Sheet, which has its own title. */
  showHeader?: boolean;
  onDeleted: () => void;
  onReupload: (doc: UserDocument) => void;
}) {
  useLocale();
  const detail = useDocument(listDoc.id, listDoc.status);
  const remove = useDeleteDocument();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const doc: UserDocument = detail.data ? { ...detail.data, usedFor: detail.data.usedFor.length ? detail.data.usedFor : listDoc.usedFor } : listDoc;
  const extraction = detail.data?.extraction ?? listDoc.extraction;
  const busy = doc.status === "uploaded" || doc.status === "processing";

  useEffect(() => {
    if (confirmingDelete) confirmRef.current?.focus();
  }, [confirmingDelete]);

  const destroy = () =>
    remove.mutate(doc.id, {
      onSuccess: () => {
        toast({ title: tr("copy.document_deleted_e4db4d6"), description: tr("copy.v0_and_the_details_adapt_read_from_it_are_gone_88f09f8", { v0: doc.filename }) });
        onDeleted();
      },
      onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail, tone: "error" }),
    });

  let fields: ReactNode;
  if (busy) {
    fields = <ReadingSkeleton />;
  } else if (doc.status === "failed") {
    fields = (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-line p-4">
        <p className="text-sm">{tr("copy.adapt_couldn_t_read_this_file_a_sharp_photo_in_g_384f95c")}</p>
        <Button variant="secondary" size="sm" icon={<Upload className="size-4" aria-hidden />} onClick={() => onReupload(doc)}>
          {tr("copy.upload_it_again_ab622f8")}</Button>
      </div>
    );
  } else if (extraction) {
    fields = <FieldsForm key={`${doc.id}:${doc.status}:${extraction.extractedAt}`} doc={doc} extraction={extraction} />;
  } else if (detail.isError) {
    fields = <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  } else {
    fields = <ReadingSkeleton />;
  }

  const deleteConfirmation = confirmingDelete && (
    <div role="group" aria-label={tr("copy.confirm_delete_c9f2829")} className="flex flex-col gap-3 rounded-lg border border-danger/30 bg-danger-tint p-4">
      <p className="text-sm">
        <span className="font-medium">{tr("copy.delete_f01a321")}{doc.filename}{tr("copy.text_5bab61e")}</span> {tr("copy.the_file_and_the_details_adapt_read_from_it_are__ed7d17f")}</p>
      <div className="flex flex-wrap gap-2">
        <Button ref={confirmRef} variant="danger" size="sm" loading={remove.isPending} onClick={destroy}>
          {tr("copy.delete_document_e8df0b7")}</Button>
        <Button variant="ghost" size="sm" onClick={() => setConfirmingDelete(false)} disabled={remove.isPending}>
          {tr("copy.keep_it_d9f3692")}</Button>
      </div>
    </div>
  );

  return (
    <article className="flex flex-col gap-6" aria-labelledby={showHeader ? `doc-title-${doc.id}` : undefined}>
      {showHeader && (
        <header className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id={`doc-title-${doc.id}`} className="text-xl">
              {localize(DOCUMENT_KIND_LABEL[doc.kind])}
            </h2>
            <p className="mt-0.5 flex flex-wrap gap-x-3 text-sm text-muted">
              <span className="min-w-0 truncate">{doc.filename}</span>
              <span className="tabular">{localize(formatBytes(doc.sizeBytes))}</span>
              <span>{tr("copy.uploaded_07ff788")}{localize(relativeTime(doc.createdAt))}</span>
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="size-4" aria-hidden />}
            onClick={() => setConfirmingDelete(true)}
            disabled={confirmingDelete}
          >
            {tr("copy.delete_f6fdbe4")}</Button>
        </header>
      )}

      {showHeader && deleteConfirmation}

      <PipelineSteps status={doc.status} reviewCount={reviewCount(extraction?.fields)} />

      <div className="@container">
        <div className="grid gap-6 @xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <DocumentPreview doc={doc} />
          <div className="min-w-0">{localize(fields)}</div>
        </div>
      </div>

      {doc.usedFor.length > 0 && (
        <section aria-labelledby={`used-${doc.id}`}>
          <h3 id={`used-${doc.id}`} className="text-sm font-medium">
            {tr("copy.used_for_these_steps_2d71822")}</h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {doc.usedFor.map((key) => (
              <li key={key}>
                <Link
                  to={`/journey?node=${encodeURIComponent(key)}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-xs font-medium hover:border-line-strong hover:bg-sunken"
                >
                  <Route className="size-3.5 text-subtle" aria-hidden />
                  {localize(nodeTitle(key))}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <p className="flex items-start gap-2 text-xs text-muted">
          <Lock className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
          {tr("copy.encrypted_never_saved_on_this_device_delete_it_a_864801c")}</p>
        {!showHeader && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="size-4" aria-hidden />}
            onClick={() => setConfirmingDelete(true)}
            disabled={confirmingDelete}
          >
            {tr("copy.delete_document_e8df0b7")}</Button>
        )}
      </div>
      {!showHeader && deleteConfirmation}
    </article>
  );
}
