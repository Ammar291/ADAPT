import { tr, localize, useLocale } from "@/i18n";
import { ExternalLink, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { ApprovalItem, ConsentItem } from "../conversation";
import { voice } from "../controller";

/**
 * Consequential actions wait here for a tap. Neither the model nor a spoken "yes" can
 * approve: only these buttons call the approval endpoints.
 */
export function ApprovalCard({ item }: { item: ApprovalItem }) {
  useLocale();
  const { request, state, outcome } = item;
  const deciding = state === "pending" || state === "failed" || state === "submitting";
  return (
    <section
      aria-labelledby={`${item.id}-title`}
      className="rounded-lg border-2 border-ink bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">
          {state === "approved" ? tr("copy.you_approved_this_9cac454") : state === "declined" ? tr("copy.you_declined_this_62b05a1") : tr("copy.needs_your_approval_7b842a5")}
        </p>
        {request.simulation_label && (
          <span
            className="rounded-sm border border-dashed border-ink/50 px-1.5 py-0.5 text-2xs font-medium tracking-wide text-ink"
            title={tr("copy.a_demonstration_nothing_real_is_booked_or_submit_5e2a66d")}
          >
            {localize(request.simulation_label)}
          </span>
        )}
      </div>
      <h3 id={`${item.id}-title`} className="mt-1 text-lg" dir="auto">
        {localize(request.title)}
      </h3>
      {request.summary && (
        <p className="mt-1 text-sm text-muted" dir="auto">
          {localize(request.summary)}
        </p>
      )}
      {request.consequences.length > 0 && deciding && (
        <ul className="mt-3 list-disc ps-5 text-sm" dir="auto">
          {request.consequences.map((line) => (
            <li key={line}>{localize(line)}</li>
          ))}
        </ul>
      )}
      {request.requires_user_authentication && deciding && (
        <p className="mt-3 flex gap-2 text-sm">
          <KeyRound className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
          {tr("copy.you_ll_sign_in_on_the_official_site_yourself_for_432f5e4")}</p>
      )}

      {deciding && (
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button
            variant="secondary"
            disabled={state === "submitting"}
            onClick={() => void voice.decideApproval(item.id, false)}
          >
            {tr("copy.decline_b59cf9e")}</Button>
          <Button loading={state === "submitting"} onClick={() => void voice.decideApproval(item.id, true)}>
            {tr("copy.approve_7b2c7f1")}</Button>
        </div>
      )}
      {state === "failed" && (
        <p className="mt-2 text-sm text-danger" role="alert">
          {tr("copy.your_decision_wasn_t_saved_nothing_was_done_try__5710c0d")}</p>
      )}

      {outcome && !deciding && (
        <div className="mt-3 flex flex-col items-start gap-3">
          <p className="text-sm" dir="auto">
            {localize(outcome.message)}
          </p>
          {outcome.handoffUrl && (
            <a
              href={outcome.handoffUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-on-primary hover:bg-primary-strong"
            >
              {tr("copy.continue_on_the_official_site_a372f3a")}<ExternalLink className="size-4" aria-hidden />
            </a>
          )}
        </div>
      )}
    </section>
  );
}

export function ConsentCard({ item }: { item: ConsentItem }) {
  useLocale();
  const { request, state } = item;
  const deciding = state === "pending" || state === "failed" || state === "saving";
  return (
    <section aria-labelledby={`${item.id}-title`} className="rounded-lg border-2 border-ink bg-surface p-4">
      <h3 id={`${item.id}-title`} className="text-lg">
        {localize(request.title)}
      </h3>
      <p className="mt-1 text-sm text-muted">{localize(request.detail)}</p>
      {deciding ? (
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button
            variant="secondary"
            disabled={state === "saving"}
            onClick={() => void voice.decideConsent(item.id, false)}
          >
            {tr("copy.not_now_e457149")}</Button>
          <Button loading={state === "saving"} onClick={() => void voice.decideConsent(item.id, true)}>
            {tr("copy.allow_3ad0e36")}</Button>
        </div>
      ) : (
        <p className="mt-3 text-sm">
          {state === "granted"
            ? tr("copy.allowed_you_can_turn_this_off_any_time_in_settin_be4db19")
            : tr("copy.okay_adapt_won_t_use_this_8228706")}
        </p>
      )}
      {state === "failed" && (
        <p className="mt-2 text-sm text-danger" role="alert">
          {tr("copy.your_choice_wasn_t_saved_try_again_3e9e782")}</p>
      )}
    </section>
  );
}
