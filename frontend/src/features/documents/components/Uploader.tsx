import { tr, localize, useLocale } from "@/i18n";
import { Camera, FileText, Lock, Upload } from "lucide-react";
import { useEffect, useId, useRef, useState, type DragEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { DOCUMENT_KIND_LABEL, type DocumentKind, type UserDocument } from "@/domain/documents";
import { describeError } from "@/lib/api/errors";
import { useUploadDocument } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import { useIsTouch } from "../hooks";
import { CAMERA_ACCEPT, UPLOAD_ACCEPT, isImage, validateUpload } from "../lib/documents";
import { KIND_ICON } from "./Pipeline";

export const DOCUMENT_KINDS = Object.keys(DOCUMENT_KIND_LABEL) as DocumentKind[];

const KIND_HINT: Partial<Record<DocumentKind, string>> = {
  passport: tr("copy.the_page_with_your_photo_79bdf0b", { lng: "en" }),
  identity_document: tr("copy.passport_style_photo_or_id_card_0c154ee", { lng: "en" }),
  marriage_certificate: tr("copy.for_family_visas_b7cee51", { lng: "en" }),
  tenancy_document: tr("copy.lease_or_tawtheeq_certificate_a7872ff", { lng: "en" }),
  employment_letter: tr("copy.offer_or_salary_letter_804f369", { lng: "en" }),
  business_document: tr("copy.licence_moa_or_bank_letter_3c5e663", { lng: "en" }),
};

/** "Passport" → "passport", but "ID document" stays as it is. */
export function kindNoun(kind: DocumentKind): string {
  const label = DOCUMENT_KIND_LABEL[kind];
  return /^[A-Z]{2}/.test(label) ? label : label.charAt(0).toLowerCase() + label.slice(1);
}

/**
 * Asks what the document is, takes a file (picker, camera or drag and drop), checks it and
 * sends it straight to the service. The File stays in component memory until then; it is
 * never written to storage.
 */
export function Uploader({
  open,
  onClose,
  initialKind,
  initialFile,
  preferCamera,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  initialKind: DocumentKind | null;
  initialFile: File | null;
  preferCamera: boolean;
  onUploaded: (doc: UserDocument) => void;
}) {
  useLocale();
  const upload = useUploadDocument();
  const touch = useIsTouch();
  const [kind, setKind] = useState<DocumentKind | null>(initialKind);
  // A file dropped on the page arrives with the sheet (the parent remounts it per upload).
  const [file, setFile] = useState<File | null>(() => (initialFile && validateUpload(initialFile).ok ? initialFile : null));
  const [error, setError] = useState<string | null>(() => {
    const check = initialFile ? validateUpload(initialFile) : null;
    return check && !check.ok ? check.message : null;
  });
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // A kind chosen before opening (deep link, "Upload passport") shows as a summary.
  const [choosingKind, setChoosingKind] = useState(initialKind === null);
  const fileSection = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const legendId = useId();

  const stage = (next: File | null | undefined) => {
    upload.reset();
    if (!next) return;
    const check = validateUpload(next);
    if (!check.ok) {
      setFile(null);
      setError(check.message);
      return;
    }
    setError(null);
    setFile(next);
  };

  // In-memory thumbnail of the staged photo, released as soon as it's replaced or closed.
  useEffect(() => {
    if (!file || !isImage(file.type)) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    stage(event.dataTransfer.files[0]);
  };

  const submit = () => {
    if (!file || !kind) return;
    upload.mutate(
      { file, kind },
      {
        onSuccess: (doc) => {
          setFile(null);
          onUploaded(doc);
        },
      },
    );
  };

  const uploadError = upload.error ? describeError(upload.error) : null;
  const problem = error ?? (uploadError ? [uploadError.title, uploadError.detail].filter(Boolean).join(". ") : null);

  useEffect(() => {
    if (problem) fileSection.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [problem]);
  const FileIcon = kind ? KIND_ICON[kind] : FileText;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={tr("copy.upload_a_document_f1836e2")}
      description={tr("copy.adapt_reads_the_details_for_you_to_check_before__1977209")}
      footer={
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={submit} loading={upload.isPending} disabled={!file || !kind} icon={<Upload className="size-4" aria-hidden />}>
            {kind ? tr("copy.upload_v0_5aec9e5", { v0: kindNoun(kind) }) : tr("copy.upload_document_73183a7")}
          </Button>
          <Button variant="ghost" onClick={onClose} disabled={upload.isPending}>
            {tr("copy.cancel_77dfd21")}</Button>
          {!kind && file && <span className="text-xs text-muted">{tr("copy.choose_what_it_is_first_07e4c25")}</span>}
        </div>
      }
    >
      <div className="flex flex-col gap-6">
        {!choosingKind && kind ? (
          <div>
            <p className="mb-2 text-sm font-medium">{tr("copy.what_you_re_uploading_84e0248")}</p>
            <div className="flex items-center gap-3 rounded-lg border border-primary bg-primary-tint p-3">
              <FileIcon className="size-5 shrink-0 text-primary-strong" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-primary-strong">{localize(DOCUMENT_KIND_LABEL[kind])}</span>
                {KIND_HINT[kind] && <span className="block text-2xs text-muted">{localize(KIND_HINT[kind])}</span>}
              </span>
              <Button size="sm" variant="ghost" onClick={() => setChoosingKind(true)}>
                {tr("copy.change_64fbd99")}</Button>
            </div>
          </div>
        ) : (
          <fieldset aria-labelledby={legendId}>
            <legend id={legendId} className="mb-2 text-sm font-medium">
              {tr("copy.what_are_you_uploading_2c28a6d")}</legend>
            <div className="grid grid-cols-2 gap-2">
              {DOCUMENT_KINDS.map((value) => {
                const Icon = KIND_ICON[value];
                const selected = kind === value;
                return (
                  <label
                    key={value}
                    className={cn(
                      "flex min-h-14 cursor-pointer items-start gap-2.5 rounded-lg border p-3 transition-colors",
                      "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus",
                      selected ? "border-primary bg-primary-tint" : "border-line bg-surface hover:border-line-strong",
                    )}
                  >
                    <input type="radio" name="document-kind" value={value} checked={selected} onChange={() => setKind(value)} className="sr-only" />
                    <Icon className={cn("mt-0.5 size-4 shrink-0", selected ? "text-primary-strong" : "text-subtle")} aria-hidden />
                    <span className="min-w-0">
                      <span className={cn("block text-sm leading-snug font-medium", selected && "text-primary-strong")}>{localize(DOCUMENT_KIND_LABEL[value])}</span>
                      {KIND_HINT[value] && <span className="mt-0.5 block text-2xs text-muted">{localize(KIND_HINT[value])}</span>}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        )}

        <div ref={fileSection} className="scroll-mb-4">
          <p className="mb-2 text-sm font-medium">{tr("copy.the_file_04fbc75")}</p>
          {file ? (
            <div className="flex items-center gap-3 rounded-lg border border-line bg-muted-surface p-3">
              {preview ? (
                <img src={preview} alt={""} className="size-14 shrink-0 rounded-md border border-line object-cover" />
              ) : (
                <span className="flex size-14 shrink-0 items-center justify-center rounded-md bg-sunken text-muted" aria-hidden>
                  <FileIcon className="size-6" />
                </span>
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{localize(file.name || tr("copy.photo_d01d900"))}</p>
                <p className="text-xs text-muted">
                  {localize(formatBytes(file.size))}
                  <span className="ms-2">{file.type === "application/pdf" ? tr("copy.pdf_d613d88") : tr("copy.image_50e19fd")}</span>
                </p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setFile(null)} disabled={upload.isPending}>
                {tr("copy.choose_another_49adb48")}</Button>
            </div>
          ) : (
            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                "flex flex-col gap-3 rounded-lg border border-dashed p-4 transition-colors",
                dragging ? "border-primary bg-primary-tint" : "border-line-strong bg-muted-surface",
              )}
            >
              {touch ? (
                <div className="flex flex-col gap-2">
                  <Button
                    size="lg"
                    variant={preferCamera ? "primary" : "secondary"}
                    icon={<Camera className="size-5" aria-hidden />}
                    onClick={() => cameraInput.current?.click()}
                  >
                    {tr("copy.scan_with_camera_b548bad")}</Button>
                  <Button
                    size="lg"
                    variant={preferCamera ? "secondary" : "primary"}
                    icon={<Upload className="size-5" aria-hidden />}
                    onClick={() => fileInput.current?.click()}
                  >
                    {tr("copy.choose_a_file_74b1d89")}</Button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2 py-4 text-center">
                  <Upload className="size-6 text-subtle" aria-hidden />
                  <p className="text-sm">{tr("copy.drag_a_photo_or_pdf_here_2fe1157")}</p>
                  <Button size="sm" variant="secondary" onClick={() => fileInput.current?.click()}>
                    {tr("copy.choose_a_file_74b1d89")}</Button>
                </div>
              )}
              <p className="text-center text-2xs text-subtle">{tr("copy.photos_or_pdfs_up_to_20_mb_keep_the_whole_page_i_5a0da69")}</p>
            </div>
          )}
          <input
            ref={fileInput}
            type="file"
            accept={UPLOAD_ACCEPT}
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              stage(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <input
            ref={cameraInput}
            type="file"
            accept={CAMERA_ACCEPT}
            capture="environment"
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              stage(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <div aria-live="assertive">
            {problem && (
              <p role="alert" className="mt-2 text-sm text-danger">
                {localize(problem)}
              </p>
            )}
          </div>
        </div>

        <p className="flex items-start gap-2 text-xs text-muted">
          <Lock className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
          {tr("copy.encrypted_and_sent_straight_to_adapt_nothing_is__925f2cf")}</p>
      </div>
    </Sheet>
  );
}
