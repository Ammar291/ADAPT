import { tr, localize, useLocale } from "@/i18n";
import { ExternalLink, History, KeyRound, Route, ShieldCheck } from "lucide-react";
import { Link } from "react-router";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { EmptyState, ErrorState, LoadingRows, Skeleton } from "@/components/ui/States";
import { ACTION_KIND_LABEL, domainOf } from "@/domain/common";
import type { ActionRecord } from "@/domain/documents";
import { useActions, useApprovals } from "@/lib/api/hooks";
import { relativeTime } from "@/lib/format";
import { useNodeTitles } from "../hooks";
import { ACTION_STATUS_TEXT, actionStatusTone } from "../lib/documents";

const SIMULATED_HINT = tr("copy.carried_out_by_a_simulated_service_nothing_is_re_42db4a7", { lng: "en" });

function ActionRow({ action, nodeTitle }: { action: ActionRecord; nodeTitle: (key: string) => string }) {
  useLocale();
  const handoff = action.status === "handoff_required";
  return (
    <li className="flex flex-col gap-2 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={actionStatusTone(action.status)}>{localize(ACTION_STATUS_TEXT[action.status])}</Badge>
        <Badge tone="outline">{localize(ACTION_KIND_LABEL[action.kind])}</Badge>
        {action.simulationLabel && (
          <Badge tone="simulated" title={localize(`${action.simulationLabel}: ${SIMULATED_HINT}`)}>
            {tr("copy.preview_only_2579fc4")}</Badge>
        )}
        <span className="ms-auto text-2xs text-subtle">{localize(relativeTime(action.createdAt))}</span>
      </div>
      <div>
        <p className="font-medium">{localize(action.title)}</p>
        <p className="mt-0.5 text-sm text-muted">{localize(action.message)}</p>
      </div>
      {action.externalReference && (
        <p className="text-sm">
          {tr("copy.reference_9b1fd83")}<span className="tabular font-medium">{localize(action.externalReference)}</span>
          {action.confirmationSource && (
            <span className="ms-1.5 text-xs text-muted">
              {action.confirmationSource === "user_reported" ? tr("copy.you_reported_this_bba1e21") : tr("copy.from_the_official_system_81dcb57")}
            </span>
          )}
        </p>
      )}
      {(action.handoffUrl || action.journeyNodeKey) && (
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2">
          {action.handoffUrl && (
            <a href={action.handoffUrl} target="_blank" rel="noopener noreferrer" className={buttonClass(handoff ? "primary" : "secondary", "sm")}>
              {tr("copy.continue_on_9d5570d")}{localize(domainOf(action.handoffUrl))}
              <ExternalLink className="size-3.5" aria-hidden />
              <span className="sr-only">{tr("copy.opens_the_official_site_in_a_new_tab_2cd60b0")}</span>
            </a>
          )}
          {action.journeyNodeKey && (
            <Link
              to={`/journey?node=${encodeURIComponent(action.journeyNodeKey)}`}
              className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink hover:underline hover:underline-offset-4"
            >
              <Route className="size-3.5" aria-hidden />
              {localize(nodeTitle(action.journeyNodeKey))}
            </Link>
          )}
        </div>
      )}
      {handoff && (
        <p className="flex items-start gap-2 text-xs text-muted">
          <KeyRound className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
          {tr("copy.you_finish_this_on_the_official_site_if_it_asks__5ffaa1d")}</p>
      )}
    </li>
  );
}

export function ApprovalsTab() {
  useLocale();
  const pending = useApprovals("pending");
  const actions = useActions();
  const nodeTitle = useNodeTitles();

  return (
    <div className="flex flex-col gap-10">
      <section aria-labelledby="approvals-pending">
        <div className="mb-4 max-w-2xl">
          <h2 id="approvals-pending" className="text-lg">
            {tr("copy.waiting_for_your_approval_5095847")}</h2>
          <p className="mt-1 text-sm text-muted">{tr("copy.nothing_is_sent_shared_or_booked_until_you_appro_e6191ed")}</p>
        </div>
        {pending.isPending ? (
          <div role="status" aria-label={tr("copy.loading_approvals_269edef")} className="grid gap-4 @4xl/main:grid-cols-2">
            <Skeleton className="h-72 w-full rounded-xl" />
            <Skeleton className="hidden h-72 w-full rounded-xl @4xl/main:block" />
          </div>
        ) : pending.isError ? (
          <ErrorState error={pending.error} onRetry={() => void pending.refetch()} />
        ) : pending.data.length === 0 ? (
          <EmptyState
            icon={<ShieldCheck className="size-5" aria-hidden />}
            title={tr("copy.nothing_waiting_for_your_approval_b284103")}
            description={tr("copy.when_adapt_prepares_something_that_shares_your_d_6b598be")}
          />
        ) : (
          <div className="grid items-start gap-4 @4xl/main:grid-cols-2">
            {pending.data.map((approval) => (
              <ApprovalCard key={approval.id} approval={approval} />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="actions-history">
        <div className="mb-4 max-w-2xl">
          <h2 id="actions-history" className="flex items-center gap-2 text-lg">
            <History className="size-4.5 text-subtle" aria-hidden />
            {tr("copy.actions_c3cd636")}</h2>
          <p className="mt-1 text-sm text-muted">
            {tr("copy.what_happened_after_you_approved_adapt_only_call_c4d3cc3")}</p>
        </div>
        {actions.isPending ? (
          <LoadingRows rows={2} label={tr("copy.loading_actions_c20b4d2")} />
        ) : actions.isError ? (
          <ErrorState error={actions.error} onRetry={() => void actions.refetch()} />
        ) : actions.data.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line-strong px-4 py-5 text-sm text-muted">
            {tr("copy.approved_actions_appear_here_with_a_link_to_fini_40935fe")}</p>
        ) : (
          <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
            {actions.data.map((action) => (
              <ActionRow key={action.id} action={action} nodeTitle={nodeTitle} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
