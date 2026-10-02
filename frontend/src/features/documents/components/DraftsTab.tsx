import { tr, localize, useLocale } from "@/i18n";
import { Building2, CalendarClock, Check, Copy, FilePen, FileText, ListChecks, Mail, PenLine, RotateCcw, Route, Trash2 } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { TextArea } from "@/components/ui/Field";
import { Sheet } from "@/components/ui/Sheet";
import { SourceLink } from "@/components/ui/SourceLink";
import { EmptyState, ErrorState, Skeleton, SkeletonText } from "@/components/ui/States";
import { toast } from "@/components/ui/Toast";
import { TrustBadge } from "@/components/ui/TrustBadge";
import { GENERATED_KIND_LABEL, type GeneratedDocument, type GeneratedDocumentKind, type GeneratedDocumentStatus } from "@/domain/documents";
import { describeError } from "@/lib/api/errors";
import { useGeneratedDocumentActions, useGeneratedDocuments } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDate, relativeTime } from "@/lib/format";
import { useNodeTitles } from "../hooks";
import { DRAFT_STATUS_TEXT, sortDrafts } from "../lib/documents";
import { markdownToPlainText } from "../lib/markdown";
import { Markdown } from "./Markdown";

const KIND_ICON: Record<GeneratedDocumentKind, typeof Mail> = {
  cover_letter: FileText,
  email: Mail,
  checklist: ListChecks,
  form_prefill: FilePen,
  business_summary: Building2,
  appointment_brief: CalendarClock,
  plan: Route,
};

const GROUPS: { status: GeneratedDocumentStatus; title: string }[] = [
  { status: "draft", title: tr("copy.waiting_for_your_review_8b9a44d", { lng: "en" }) },
  { status: "approved", title: tr("copy.approved_41b81eb", { lng: "en" }) },
  { status: "discarded", title: tr("copy.discarded_7ecfbf0", { lng: "en" }) },
];

const STATUS_TONE: Record<GeneratedDocumentStatus, "ink" | "primary" | "neutral"> = { draft: "ink", approved: "primary", discarded: "neutral" };

function toastError(error: unknown) {
  const { title, detail } = describeError(error);
  toast({ title, description: detail, tone: "error" });
}

// --- editor state shared by the panel and the phone sheet ---------------------------------------

function useDraftEditor(draft: GeneratedDocument) {
  const actions = useGeneratedDocumentActions();
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(draft.bodyMarkdown);
  const dirty = body !== draft.bodyMarkdown;

  const startEditing = () => {
    setBody(draft.bodyMarkdown);
    setEditing(true);
  };
  const cancel = () => {
    setBody(draft.bodyMarkdown);
    setEditing(false);
  };
  const save = () =>
    actions.update.mutate(
      { id: draft.id, body },
      {
        onSuccess: () => {
          setEditing(false);
          toast({ title: tr("copy.changes_saved_0bbe9ed") });
        },
        onError: toastError,
      },
    );
  const approve = () =>
    actions.approve.mutate(draft.id, {
      onSuccess: () => toast({ title: tr("copy.draft_approved_7105098"), description: tr("copy.it_s_ready_to_use_copy_the_text_when_you_need_it_2c35c43") }),
      onError: toastError,
    });
  const discard = () =>
    actions.discard.mutate(draft.id, {
      onSuccess: () => toast({ title: tr("copy.draft_discarded_054d664"), description: tr("copy.you_can_restore_it_from_discarded_d9a8488"), tone: "info" }),
      onError: toastError,
    });
  const restore = () =>
    actions.update.mutate({ id: draft.id, body: draft.bodyMarkdown }, { onSuccess: () => toast({ title: tr("copy.draft_restored_2bf17e1") }), onError: toastError });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdownToPlainText(editing ? body : draft.bodyMarkdown));
      toast({ title: tr("copy.text_copied_4aeba8f"), description: tr("copy.paste_it_into_your_email_or_the_official_form_fce9264") });
    } catch {
      toast({ title: tr("copy.couldn_t_copy_d1e1e10"), description: tr("copy.select_the_text_and_copy_it_instead_94471aa"), tone: "error" });
    }
  };

  return { draft, actions, editing, body, setBody, dirty, startEditing, cancel, save, approve, discard, restore, copy };
}

type DraftEditor = ReturnType<typeof useDraftEditor>;

function DraftBody({ editor, nodeTitle, showTitle }: { editor: DraftEditor; nodeTitle: (key: string) => string; showTitle: boolean }) {
  useLocale();
  const { draft, editing, body, setBody } = editor;
  const citations = draft.evidence.citations;
  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATUS_TONE[draft.status]}>{draft.status === "draft" ? tr("copy.draft_for_your_review_7b0bfff") : DRAFT_STATUS_TEXT[draft.status]}</Badge>
          <Badge tone="outline">{localize(GENERATED_KIND_LABEL[draft.kind])}</Badge>
          <TrustBadge kind={draft.evidence.kind} />
        </div>
        {showTitle && <h2 className="mt-3 text-xl">{localize(draft.title)}</h2>}
        <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
          <span>{tr("copy.updated_c95815a")}{localize(relativeTime(draft.updatedAt))}</span>
          {draft.journeyNodeKey && (
            <Link
              to={`/journey?node=${encodeURIComponent(draft.journeyNodeKey)}`}
              className="inline-flex items-center gap-1.5 text-ink hover:underline hover:underline-offset-4"
            >
              <Route className="size-3.5 text-subtle" aria-hidden />
              {tr("copy.for_2dc01b8")}{localize(nodeTitle(draft.journeyNodeKey))}
            </Link>
          )}
        </p>
      </div>

      {editing ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`draft-body-${draft.id}`} className="text-sm font-medium">
            {tr("copy.edit_the_text_85129b2")}</label>
          <TextArea
            id={`draft-body-${draft.id}`}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={16}
            className="min-h-72 resize-y font-sans"
            aria-describedby={`draft-hint-${draft.id}`}
          />
          <p id={`draft-hint-${draft.id}`} className="text-xs text-subtle">
            {tr("copy.formatting_bold_lines_starting_with_for_lists_an_b1a39ce")}</p>
        </div>
      ) : (
        <div className={cn("rounded-lg border border-line bg-surface px-5 py-5 sm:px-7 sm:py-6", draft.status === "discarded" && "opacity-70")}>
          <Markdown source={draft.bodyMarkdown} className="max-w-prose text-[0.95rem]" />
        </div>
      )}

      {(draft.evidence.note || citations.length > 0) && (
        <div className="flex flex-col gap-2">
          {draft.evidence.note && <p className="text-sm text-muted">{localize(draft.evidence.note)}</p>}
          {citations.length > 0 && (
            <ul className="flex flex-col gap-2">
              {citations.map((c) => (
                <li key={c.url}>
                  <SourceLink title={localize(c.title)} url={c.url} authority={c.authority} checkedAt={c.retrievedAt} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function DraftActions({ editor, className }: { editor: DraftEditor; className?: string }) {
  useLocale();
  const { draft, actions, editing, dirty } = editor;
  const busy = actions.update.isPending || actions.approve.isPending || actions.discard.isPending;
  if (editing) {
    return (
      <div className={cn("flex flex-wrap items-center gap-2", className)}>
        <Button onClick={editor.save} loading={actions.update.isPending} disabled={!dirty}>
          {tr("copy.save_changes_179359b")}</Button>
        <Button variant="ghost" onClick={editor.cancel} disabled={busy}>
          {tr("copy.cancel_77dfd21")}</Button>
      </div>
    );
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {draft.status === "draft" && (
        <Button onClick={editor.approve} loading={actions.approve.isPending} disabled={busy} icon={<Check className="size-4" aria-hidden />}>
          {tr("copy.approve_draft_0b5ceab")}</Button>
      )}
      {draft.status === "discarded" && (
        <Button
          variant="secondary"
          onClick={editor.restore}
          loading={actions.update.isPending}
          disabled={busy}
          icon={<RotateCcw className="size-4" aria-hidden />}
        >
          {tr("copy.restore_draft_ab300c4")}</Button>
      )}
      {draft.status === "draft" && (
        <Button variant="secondary" onClick={editor.startEditing} disabled={busy} icon={<PenLine className="size-4" aria-hidden />}>
          {tr("copy.edit_5301648")}</Button>
      )}
      <Button variant="secondary" onClick={() => void editor.copy()} icon={<Copy className="size-4" aria-hidden />}>
        {tr("copy.copy_text_06a76cc")}</Button>
      {draft.status === "draft" && (
        <Button
          variant="ghost"
          onClick={editor.discard}
          loading={actions.discard.isPending}
          disabled={busy}
          icon={<Trash2 className="size-4" aria-hidden />}
          className="sm:ms-auto"
        >
          {tr("copy.discard_36fff63")}</Button>
      )}
      {draft.status === "approved" && (
        <span className="text-xs text-muted sm:ms-auto">{tr("copy.approved_afd61f8")}{localize(formatDate(draft.updatedAt))}{tr("copy.ask_adapt_for_a_new_draft_to_change_it_5cf4667")}</span>
      )}
    </div>
  );
}

// --- list -----------------------------------------------------------------------------------------

function DraftList({
  drafts,
  selectedId,
  onSelect,
  nodeTitle,
  opensDialog,
}: {
  drafts: GeneratedDocument[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  nodeTitle: (key: string) => string;
  opensDialog: boolean;
}) {
  useLocale();
  return (
    <div>
      {GROUPS.map((group) => {
        const items = drafts.filter((d) => d.status === group.status);
        if (!items.length) return null;
        return (
          <section key={group.status} aria-labelledby={`drafts-${group.status}`} className="border-b border-line last:border-b-0">
            <h3 id={`drafts-${group.status}`} className="flex items-center gap-2 px-4 pt-4 pb-1 font-sans text-xs font-medium text-muted sm:px-5">
              {localize(group.title)}
              <span className="tabular text-subtle">{localize(items.length)}</span>
            </h3>
            <ul className="divide-y divide-line">
              {items.map((draft) => {
                const Icon = KIND_ICON[draft.kind];
                const selected = draft.id === selectedId;
                return (
                  <li
                    key={draft.id}
                    className={cn("relative flex gap-3 px-4 py-3.5 transition-colors sm:px-5", selected ? "bg-primary-tint/60" : "hover:bg-muted-surface")}
                  >
                    {selected && <span className="absolute inset-y-2 start-0 w-0.5 rounded-full bg-primary" aria-hidden />}
                    <span
                      className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md", selected ? "bg-surface" : "bg-sunken", "text-muted")}
                      aria-hidden
                    >
                      <Icon className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <button
                        type="button"
                        onClick={() => onSelect(draft.id)}
                        aria-current={!opensDialog && selected ? "true" : undefined}
                        aria-haspopup={opensDialog ? "dialog" : undefined}
                        className={cn(
                          "block w-full text-start text-sm leading-snug font-medium after:absolute after:inset-0 after:content-['']",
                          draft.status === "discarded" && "text-muted",
                        )}
                      >
                        {localize(draft.title)}
                        <span className="sr-only">{tr("copy.text_d3bc9a3")}{localize(DRAFT_STATUS_TEXT[draft.status])}</span>
                      </button>
                      <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted">
                        <span>{localize(GENERATED_KIND_LABEL[draft.kind])}</span>
                        {draft.journeyNodeKey && <span className="truncate">{tr("copy.for_2dc01b8")}{localize(nodeTitle(draft.journeyNodeKey))}</span>}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function PanelDraft({ draft, nodeTitle }: { draft: GeneratedDocument; nodeTitle: (key: string) => string }) {
  useLocale();
  const editor = useDraftEditor(draft);
  return (
    <div className="flex flex-col gap-6">
      <DraftBody editor={editor} nodeTitle={nodeTitle} showTitle />
      <DraftActions editor={editor} className="border-t border-line pt-4" />
      <p className="text-2xs text-subtle">{tr("copy.adapt_drafted_this_from_your_plan_read_it_throug_6a19c47")}</p>
    </div>
  );
}

function SheetDraft({ draft, nodeTitle, open, onClose }: { draft: GeneratedDocument; nodeTitle: (key: string) => string; open: boolean; onClose: () => void }) {
  useLocale();
  const editor = useDraftEditor(draft);
  return (
    <Sheet open={open} onClose={onClose} title={localize(draft.title)} tall footer={<DraftActions editor={editor} />}>
      <DraftBody editor={editor} nodeTitle={nodeTitle} showTitle={false} />
      <p className="mt-5 text-2xs text-subtle">{tr("copy.adapt_drafted_this_from_your_plan_read_it_throug_6a19c47")}</p>
    </Sheet>
  );
}

export function DraftsTab({ selectedId, onSelect, wide }: { selectedId: string | null; onSelect: (id: string | null) => void; wide: boolean }) {
  useLocale();
  const isDesktop = wide;
  const query = useGeneratedDocuments();
  const nodeTitle = useNodeTitles();
  const reduce = useReducedMotion();
  const lastSheetDraft = useRef<GeneratedDocument | null>(null);

  if (query.isPending) {
    return (
      <div role="status" aria-label={tr("copy.loading_drafts_682afcf")} className="grid gap-6 @4xl/main:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <Skeleton className="h-72 w-full rounded-xl" />
        <div className="hidden rounded-xl border border-line bg-surface p-6 @4xl/main:block">
          <Skeleton className="h-6 w-1/2" />
          <SkeletonText lines={8} className="mt-6" />
        </div>
      </div>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const drafts = sortDrafts(query.data);
  if (!drafts.length) {
    return (
      <EmptyState
        icon={<FilePen className="size-5" aria-hidden />}
        title={tr("copy.no_drafts_yet_3f3203a")}
        description={tr("copy.as_your_plan_moves_along_adapt_drafts_cover_lett_764b7c8")}
        action={
          <Link to="/journey" className="text-sm font-medium text-primary-strong underline underline-offset-4">
            {tr("copy.go_to_your_journey_b814303")}</Link>
        }
      />
    );
  }

  const explicit = drafts.find((d) => d.id === selectedId) ?? null;
  const selected = explicit ?? (isDesktop ? drafts[0]! : null);
  if (!isDesktop && explicit) lastSheetDraft.current = explicit;
  const sheetDraft = lastSheetDraft.current;

  return (
    <div className="grid items-start gap-6 @4xl/main:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
      <Card tone="raised" className="overflow-hidden">
        <DraftList drafts={drafts} selectedId={selected?.id ?? null} onSelect={onSelect} nodeTitle={nodeTitle} opensDialog={!isDesktop} />
      </Card>
      {isDesktop && selected && (
        <Card tone="strong" className="p-6 @6xl/main:p-8">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={selected.id}
              initial={reduce ? false : { opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={reduce ? undefined : { opacity: 0 }}
              transition={{ duration: 0.18, ease: [0.2, 0, 0, 1] }}
            >
              <PanelDraft key={`${selected.id}:${selected.updatedAt}`} draft={selected} nodeTitle={nodeTitle} />
            </motion.div>
          </AnimatePresence>
        </Card>
      )}
      {!isDesktop && sheetDraft && (
        <SheetDraft
          key={sheetDraft.id}
          draft={drafts.find((d) => d.id === sheetDraft.id) ?? sheetDraft}
          nodeTitle={nodeTitle}
          open={Boolean(explicit)}
          onClose={() => onSelect(null)}
        />
      )}
    </div>
  );
}
