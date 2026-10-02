import { tr, localize, useLocale } from "@/i18n";
/**
 * Documents: what the user uploaded and what ADAPT read from it, drafts ADAPT wrote for
 * them, and actions waiting for their approval.
 *
 * Deep links: `?upload=<kind>` opens the uploader with that kind chosen, `?draft=<id>` opens
 * a draft, `?tab=drafts|approvals` picks a tab, `?doc=<id>` opens a document.
 */
import { Camera, LockKeyhole, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Button } from "@/components/ui/Button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Controls";
import { PageHeader } from "@/components/ui/PageHeader";
import { toast } from "@/components/ui/Toast";
import { DOCUMENT_KIND_LABEL, type DocumentKind, type UserDocument } from "@/domain/documents";
import { useApprovals, useDocuments, useGeneratedDocuments } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { ApprovalsTab } from "./components/ApprovalsTab";
import { DocumentsTab, type UploadRequest } from "./components/DocumentsTab";
import { DraftsTab } from "./components/DraftsTab";
import { DOCUMENT_KINDS, Uploader } from "./components/Uploader";
import { SPLIT_MIN_WIDTH, useElementWidth, useIsTouch } from "./hooks";
import { parseDocumentKind } from "./lib/documents";

const TABS = ["documents", "drafts", "approvals"] as const;
type Tab = (typeof TABS)[number];

interface UploaderSession {
  id: number;
  kind: DocumentKind | null;
  file: File | null;
  camera: boolean;
}

function Count({ value, attention, label }: { value: number | undefined; attention?: boolean; label: string }) {
  useLocale();
  if (value === undefined) return null;
  return (
    <>
      <span
        aria-hidden
        className={cn(
          "tabular inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-2xs font-medium",
          attention && value > 0 ? "bg-ink text-canvas" : "bg-sunken text-muted",
        )}
      >
        {localize(value)}
      </span>
      <span className="sr-only">{tr("copy.text_d3bc9a3")}{localize(label)}</span>
    </>
  );
}

export default function DocumentsPage() {
  const uiLocale = useLocale();
  const [params, setParams] = useSearchParams();
  const touch = useIsTouch();
  const documents = useDocuments();
  const drafts = useGeneratedDocuments();
  const approvals = useApprovals("pending");
  // The uploader is unmounted when it closes, so a picked File never outlives the sheet.
  const [uploader, setUploader] = useState<UploaderSession | null>(null);
  const sessions = useRef(0);
  const closeUploader = useCallback(() => setUploader(null), [uiLocale]);
  const [pageRef, pageWidth] = useElementWidth<HTMLDivElement>();
  const wide = pageWidth >= SPLIT_MIN_WIDTH;

  const draftId = params.get("draft");
  const requestedTab = params.get("tab");
  const tab: Tab = draftId ? "drafts" : TABS.includes(requestedTab as Tab) ? (requestedTab as Tab) : "documents";
  const docId = params.get("doc");

  const update = useCallback(
    (change: (next: URLSearchParams) => void) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          change(next);
          return next;
        },
        { replace: true },
      ),
    [setParams, uiLocale],
  );

  const openUploader = useCallback((request: UploadRequest = {}) => {
    sessions.current += 1;
    setUploader({ id: sessions.current, kind: request.kind ?? null, file: request.file ?? null, camera: Boolean(request.camera) });
  }, [uiLocale]);

  // `?upload=<kind>` opens the uploader once, with that kind chosen.
  const uploadParam = params.get("upload");
  useEffect(() => {
    if (uploadParam === null) return;
    openUploader({ kind: parseDocumentKind(uploadParam, DOCUMENT_KINDS) });
    update((next) => next.delete("upload"));
  }, [uploadParam, openUploader, update]);

  const setTab = (value: string) =>
    update((next) => {
      if (value === "documents") next.delete("tab");
      else next.set("tab", value);
      if (value !== "drafts") next.delete("draft");
      if (value !== "documents") next.delete("doc");
    });

  const selectDocument = (id: string | null) =>
    update((next) => {
      if (id) next.set("doc", id);
      else next.delete("doc");
    });

  const selectDraft = (id: string | null) =>
    update((next) => {
      next.set("tab", "drafts");
      if (id) next.set("draft", id);
      else next.delete("draft");
    });

  const onUploaded = (doc: UserDocument) => {
    closeUploader();
    toast({
      title: tr("copy.v0_uploaded_01f32ee", { v0: localize(DOCUMENT_KIND_LABEL[doc.kind]) }),
      description: tr("copy.adapt_is_reading_it_now_the_details_appear_here__cce486a"),
    });
    update((next) => {
      next.delete("tab");
      next.delete("draft");
      next.set("doc", doc.id);
    });
  };

  const docCount = documents.data?.length;
  const draftCount = drafts.data?.filter((d) => d.status === "draft").length;
  const approvalCount = approvals.data?.length;
  // The empty state carries its own upload buttons; don't repeat them in the header.
  const noDocumentsYet = tab === "documents" && docCount === 0;

  return (
    <div ref={pageRef} className="flex flex-col">
      <PageHeader
        title={tr("copy.documents_687c828")}
        description={tr("copy.your_documents_prepared_drafts_and_approvals_rev_58fe3b4")}
        actions={
          noDocumentsYet ? undefined : (
            <>
              {touch && (
                <Button variant="secondary" icon={<Camera className="size-4" aria-hidden />} onClick={() => openUploader({ camera: true })}>
                  {tr("copy.scan_with_camera_b548bad")}</Button>
              )}
              <Button icon={<Upload className="size-4" aria-hidden />} onClick={() => openUploader()}>
                {tr("copy.upload_a_document_f1836e2")}</Button>
            </>
          )
        }
      />

      <div className="private-banner mb-5 flex items-center gap-3 rounded-xl px-4 py-3"><LockKeyhole className="size-4 shrink-0 text-primary" aria-hidden /><p className="text-xs text-muted"><span className="font-medium text-ink">{tr("copy.your_private_document_space_60f1802")}</span> {tr("copy.encrypted_visible_only_to_you_and_never_cached_f_ad9a11b")}</p></div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList label={tr("copy.documents_sections_c0a20ca")} className="mb-6">
          <TabsTrigger value="documents">
            <span className="@lg/main:hidden">{tr("copy.documents_687c828")}</span>
            <span className="hidden @lg/main:inline">{tr("copy.your_documents_8485be9")}</span>
            <Count value={docCount} label={localize(tr("copy.v0_documents_18b0244", { v0: docCount ?? 0 }))} />
          </TabsTrigger>
          <TabsTrigger value="drafts">
            <span className="@lg/main:hidden">{tr("copy.drafts_22a31d8")}</span>
            <span className="hidden @lg/main:inline">{tr("copy.drafted_for_you_e0c432a")}</span>
            <Count value={draftCount} attention label={localize(tr("copy.v0_to_review_fcf61fe", { v0: draftCount ?? 0 }))} />
          </TabsTrigger>
          <TabsTrigger value="approvals">
            {tr("copy.approvals_deb9d03")}<Count value={approvalCount} attention label={localize(tr("copy.v0_waiting_9cf4230", { v0: approvalCount ?? 0 }))} />
          </TabsTrigger>
        </TabsList>

        <TabsContent value="documents">
          <DocumentsTab selectedId={docId} onSelect={selectDocument} onUpload={openUploader} wide={wide} />
        </TabsContent>
        <TabsContent value="drafts">
          <DraftsTab selectedId={draftId} onSelect={selectDraft} wide={wide} />
        </TabsContent>
        <TabsContent value="approvals">
          <ApprovalsTab />
        </TabsContent>
      </Tabs>

      {uploader && (
        <Uploader
          key={uploader.id}
          open
          onClose={closeUploader}
          initialKind={uploader.kind}
          initialFile={uploader.file}
          preferCamera={uploader.camera}
          onUploaded={onUploaded}
        />
      )}
    </div>
  );
}
