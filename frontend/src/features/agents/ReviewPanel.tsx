import { tr, localize, useLocale } from "@/i18n";
import { ExternalLink, Hand, Lock, ShieldCheck } from "lucide-react";
import { useEffect, useState, type Ref } from "react";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { toast } from "@/components/ui/Toast";
import { domainOf } from "@/domain/common";
import { DOCUMENT_KIND_LABEL, type DocumentCorrectionItem, type Review, type SubmissionConfirmationItem, type SubmissionOutcome } from "@/domain/documents";
import { describeError } from "@/lib/api/errors";
import { useResumeRun, useRunReview } from "@/lib/api/hooks";
import type { RunView } from "@/lib/events/runEvents";
import { cn } from "@/lib/cn";
import { buildConfirmationAnswer, buildCorrectionAnswer, confirmationErrors, OUTCOME_LABEL, type ConfirmationDraft, type CorrectionEdits } from "./review";

function OfficialLink({ url }: { url: string }) {
  useLocale();
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs font-medium text-primary-strong underline-offset-4 hover:underline"
    >
      {tr("copy.official_page_9bd4d7c")}{localize(domainOf(url))}
      <ExternalLink className="size-3" aria-hidden />
      <span className="sr-only">{tr("copy.opens_in_a_new_tab_bf5b990")}</span>
    </a>
  );
}

function ActionApprovals({ review }: { review: Extract<Review, { gate: "action_approval" }> }) {
  useLocale();
  return (
    <div className="flex flex-col gap-3">
      {review.items.map((approval) => (
        <div key={approval.id} className="flex flex-col gap-1.5">
          <ApprovalCard approval={approval} />
          {(approval.officialUrl || !approval.reversible) && approval.status === "pending" && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs text-muted">
              {!approval.reversible && (
                <span className="inline-flex items-center gap-1">
                  <Lock className="size-3" aria-hidden />
                  {tr("copy.can_t_be_undone_once_it_s_sent_120890d")}</span>
              )}
              {approval.officialUrl && <OfficialLink url={approval.officialUrl} />}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function DocumentCorrections({ review }: { review: Extract<Review, { gate: "document_correction" }> }) {
  useLocale();
  const resume = useResumeRun();
  const [edits, setEdits] = useState<CorrectionEdits>({});
  const setField = (doc: DocumentCorrectionItem, name: string, value: string) =>
    setEdits((prev) => ({ ...prev, [doc.documentId]: { ...prev[doc.documentId], [name]: value } }));

  const submit = () =>
    resume.mutate(
      { runId: review.runId, reviewId: review.reviewId, answer: buildCorrectionAnswer(review.items, edits) },
      {
        onSuccess: () => toast({ title: tr("copy.details_confirmed_59f184e"), description: tr("copy.adapt_is_carrying_on_with_your_plan_714ac37") }),
        onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail ?? undefined, tone: "error" }),
      },
    );

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {review.items.map((doc) => (
        <fieldset key={doc.documentId} className="rounded-xl border border-line bg-surface p-4">
          <legend className="px-1 text-sm font-medium">
            {localize(DOCUMENT_KIND_LABEL[doc.kind])}
            {doc.holder ? ` (${doc.holder})` : ""}
          </legend>
          <div className="mt-1 grid gap-3 sm:grid-cols-2">
            {doc.fields.map((field) => (
              <Field
                key={field.name}
                label={
                  <span className="inline-flex items-center gap-2">
                    {localize(field.label)}
                    {field.needsReview && <Badge tone="ink">{tr("copy.check_this_595cd6d")}</Badge>}
                  </span>
                }
                hint={field.needsReview ? tr("copy.adapt_is_v0_sure_it_read_this_correctly_7131a97", { v0: Math.round(field.confidence * 100) }) : undefined}
              >
                {localize((props) => (
                  <TextInput
                    {...props}
                    value={edits[doc.documentId]?.[field.name] ?? field.value ?? ""}
                    onChange={(e) => setField(doc, field.name, e.target.value)}
                    className={cn(field.needsReview && "border-ink/60")}
                  />
                ))}
              </Field>
            ))}
          </div>
        </fieldset>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" loading={resume.isPending}>
          {tr("copy.confirm_details_and_continue_83d5508")}</Button>
        <span className="text-xs text-muted">{tr("copy.only_what_you_change_is_corrected_1bf6d8d")}</span>
      </div>
    </form>
  );
}

const OUTCOMES: SubmissionOutcome[] = ["submitted", "completed", "not_yet", "could_not_complete"];

function SubmissionConfirmations({ review }: { review: Extract<Review, { gate: "submission_confirmation" }> }) {
  useLocale();
  const resume = useResumeRun();
  const [drafts, setDrafts] = useState<Record<string, ConfirmationDraft>>({});
  const [showErrors, setShowErrors] = useState(false);
  const errors = confirmationErrors(review.items, drafts);
  const update = (item: SubmissionConfirmationItem, patch: Partial<ConfirmationDraft>) =>
    setDrafts((prev) => ({ ...prev, [item.actionId]: { outcome: null, reference: "", note: "", ...prev[item.actionId], ...patch } }));

  const submit = () => {
    if (Object.keys(errors).length) {
      setShowErrors(true);
      return;
    }
    resume.mutate(
      { runId: review.runId, reviewId: review.reviewId, answer: buildConfirmationAnswer(review.items, drafts) },
      {
        onSuccess: () => toast({ title: tr("copy.thanks_noted_26fc13a"), description: tr("copy.adapt_updated_your_plan_with_what_happened_8e21da5") }),
        onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail ?? undefined, tone: "error" }),
      },
    );
  };

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {review.items.map((item) => {
        const draft = drafts[item.actionId];
        const error = showErrors ? errors[item.actionId] : undefined;
        return (
          <fieldset
            key={item.actionId}
            className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4"
            aria-describedby={error ? `${item.actionId}-err` : undefined}
          >
            <legend className="sr-only">{localize(item.title)}</legend>
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{localize(item.title)}</p>
              {item.simulationLabel && <Badge tone="dune">{localize(item.simulationLabel)}</Badge>}
            </div>
            {item.officialUrl && <OfficialLink url={item.officialUrl} />}
            <div role="radiogroup" aria-label={localize(tr("copy.what_happened_with_v0_48db090", { v0: item.title }))} className="flex flex-wrap gap-2">
              {OUTCOMES.map((outcome) => (
                <label
                  key={outcome}
                  className={cn(
                    "inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-focus",
                    draft?.outcome === outcome ? "border-ink bg-ink text-canvas" : "border-line-strong hover:bg-sunken",
                  )}
                >
                  <input
                    type="radio"
                    name={`outcome-${item.actionId}`}
                    value={outcome}
                    checked={draft?.outcome === outcome}
                    onChange={() => update(item, { outcome })}
                    className="sr-only"
                  />
                  {localize(OUTCOME_LABEL[outcome])}
                </label>
              ))}
            </div>
            {(draft?.outcome === "completed" || draft?.outcome === "submitted") && (
              <Field
                label={tr("copy.reference_number_ea10bb6")}
                optional={draft.outcome !== "completed"}
                hint={tr("copy.from_the_official_confirmation_email_or_page_4d92939")}
                error={error && draft.outcome === "completed" ? error : null}
              >
                {localize((props) => <TextInput {...props} value={draft.reference} onChange={(e) => update(item, { reference: e.target.value })} />)}
              </Field>
            )}
            <Field label={tr("copy.anything_adapt_should_know_c106b01")} optional>
              {localize((props) => <TextInput {...props} value={draft?.note ?? ""} onChange={(e) => update(item, { note: e.target.value })} />)}
            </Field>
            {error && !(draft?.outcome === "completed") && (
              <p id={`${item.actionId}-err`} className="text-xs text-danger">
                {localize(error)}
              </p>
            )}
          </fieldset>
        );
      })}
      <div>
        <Button type="submit" loading={resume.isPending}>
          {tr("copy.send_and_continue_131b37b")}</Button>
      </div>
    </form>
  );
}

/**
 * The human checkpoint of a paused run, shown prominently until the person decides.
 * Nothing is sent, booked or submitted before that.
 */
export function ReviewPanel({
  runId,
  view,
  ref,
  onLoaded,
  className,
}: {
  runId: string;
  view: RunView;
  ref?: Ref<HTMLElement>;
  /** Called once the review's items have loaded (e.g. to bring it into view). */
  onLoaded?: () => void;
  className?: string;
}) {
  useLocale();
  const review = useRunReview(runId, true);
  const loadedId = review.data?.reviewId;
  useEffect(() => {
    if (loadedId) onLoaded?.();
    // Only when a new review arrives, not when the callback identity changes.
  }, [loadedId]);
  const gate = review.data?.gate;
  const { refetch } = review;
  const missing = review.data === null;
  // The approval can arrive a moment before the run records its pause: look again once it has.
  useEffect(() => {
    if (view.status === "awaiting_input" && missing) void refetch();
  }, [view.status, missing, refetch]);
  const title =
    gate === "document_correction" ? tr("copy.check_what_adapt_read_57f621a") : gate === "submission_confirmation" ? tr("copy.tell_adapt_what_happened_f30bb39") : tr("copy.requires_your_approval_927e02e");
  const intro =
    gate === "document_correction"
      ? tr("copy.confirm_or_correct_these_details_so_adapt_can_fi_c9c2a65")
      : gate === "submission_confirmation"
          ? tr("copy.your_report_stays_with_the_official_handoff_a_pr_ef2936b")
        : tr("copy.adapt_paused_before_doing_anything_on_your_behal_e8fbbb4");

  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-labelledby="review-title"
      className={cn("scroll-mt-4 rounded-xl border-2 border-ink bg-surface shadow-raised focus:outline-none", className)}
    >
      <div className="flex items-start gap-3 border-b border-line px-4 py-3.5 sm:px-5">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-canvas">
          <Hand className="size-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <h2 id="review-title" className="text-lg leading-snug">
            {localize(title)}
          </h2>
          <p className="mt-0.5 text-sm text-muted">{localize(intro)}</p>
        </div>
      </div>
      <div className="p-3 sm:p-4">
        {review.isPending ? (
          <div role="status" aria-label={tr("copy.loading_your_review_25121af")} className="flex flex-col gap-3">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-9 w-40" />
          </div>
        ) : review.isError ? (
          <ErrorState error={review.error} onRetry={() => void review.refetch()} />
        ) : !review.data ? (
          <div className="flex flex-col gap-2 p-1">
            {view.pendingApprovals.map((a) => (
              <p key={a.approvalId} className="text-sm">
                <span className="font-medium">{localize(a.title)}</span>
                <span className="block text-muted">{localize(a.summary)}</span>
              </p>
            ))}
            <p className="flex items-center gap-2 text-sm text-muted">
              <ShieldCheck className="size-4 text-primary" aria-hidden />
              {tr("copy.waiting_for_your_review_to_load_it_also_appears__b19e7bf")}</p>
          </div>
        ) : review.data.gate === "action_approval" ? (
          <ActionApprovals review={review.data} />
        ) : review.data.gate === "document_correction" ? (
          <DocumentCorrections review={review.data} />
        ) : (
          <SubmissionConfirmations review={review.data} />
        )}
      </div>
    </section>
  );
}
