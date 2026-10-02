import { tr, localize, useLocale } from "@/i18n";
import { ExternalLink, KeyRound, RotateCcw, ShieldAlert } from "lucide-react";
import { Link } from "react-router";
import { ACTION_KIND_LABEL } from "@/domain/common";
import type { Approval } from "@/domain/documents";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { ACTION_CARD_HINT } from "@/lib/actionCard";
import { useDecideApproval } from "@/lib/api/hooks";
import { describeError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { relativeTime } from "@/lib/format";

/** "missing_documents" → "Missing documents"; labels already in words pass through. */
function humanise(key: string): string {
  if (!/[_.]/.test(key) && /[A-Z ]/.test(key)) return key;
  const words = key.replace(/[_.]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * A consequential action waiting for the user's decision: what will happen, exactly what
 * will be shared, and whether it's simulated. Nothing happens until they approve.
 */
export function ApprovalCard({ approval, compact = false, className }: { approval: Approval; compact?: boolean; className?: string }) {
  useLocale();
  const decide = useDecideApproval();
  const pending = approval.status === "pending";
  const entries = Object.entries(approval.payloadPreview);

  const run = (decision: "approve" | "reject") =>
    decide.mutate(
      { id: approval.id, decision },
      {
        onSuccess: (result) =>
          toast({
            title: decision === "approve" ? tr("copy.approved_41b81eb") : tr("copy.not_now_e457149"),
            description:
              decision === "approve"
                ? result.officialUrl
                  ? tr("copy.your_details_are_ready_finish_on_the_official_pa_7ffb673")
                  : tr("copy.adapt_has_recorded_your_approval_e0a9b99")
                : tr("copy.nothing_was_sent_you_can_prepare_it_again_later_39df726"),
          }),
        onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail, tone: "error" }),
      },
    );

  return (
    <article
      className={cn("rounded-xl border bg-surface", pending ? "border-dune/50 border-t-4 shadow-card" : "border-line", className)}
      aria-label={localize(tr("copy.approval_v0_1add21a", { v0: approval.title }))}
    >
      <div className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={pending ? "ink" : approval.status === "approved" ? "primary" : "neutral"}>
            {pending ? tr("copy.approval_required_b8d012c") : approval.status === "approved" ? tr("copy.approved_41b81eb") : tr("copy.declined_ff59b80")}
          </Badge>
          <Badge tone="outline">{localize(ACTION_KIND_LABEL[approval.actionKind])}</Badge>
          {approval.simulationLabel && (
            <Badge tone="simulated" title={`${approval.simulationLabel}: ${localize(ACTION_CARD_HINT["Demo adapter"])}`}>
              {tr("copy.preview_only_2579fc4")}</Badge>
          )}
          <span className="ms-auto text-2xs text-subtle">{localize(relativeTime(approval.decidedAt ?? approval.createdAt))}</span>
        </div>
        <div>
          <h3 className="text-base font-medium">{localize(approval.title)}</h3>
          <p className="mt-0.5 text-sm text-muted">{localize(approval.summary)}</p>
        </div>

        {!compact && approval.consequences.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-muted">{tr("copy.what_happens_if_you_approve_3c93f9e")}</p>
            <ul className="flex flex-col gap-1 text-sm">
              {approval.consequences.map((c) => (
                <li key={c} className="flex gap-2">
                  <ShieldAlert className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />
                  {localize(c)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {!compact && entries.length > 0 && (
          <div className="rounded-lg bg-sunken p-3">
            <p className="mb-1.5 text-xs font-medium text-muted">{tr("copy.exactly_what_will_be_shared_3fa812c")}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              {entries.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="text-muted">{localize(humanise(key))}</dt>
                  <dd className="min-w-0 break-words">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {approval.requiresUserAuthentication && (
          <p className="flex items-start gap-2 text-xs text-muted">
            <KeyRound className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
            {tr("copy.you_sign_in_with_uae_pass_on_the_official_site_a_295d4cd")}</p>
        )}
        {approval.journeyNodeKey && (
          <Link to={`/journey?node=${approval.journeyNodeKey}`} className="text-xs font-medium text-primary-strong underline-offset-4 hover:underline">
            {tr("copy.see_this_step_in_your_journey_62d5afe")}</Link>
        )}
        {!pending && approval.status === "approved" && approval.officialUrl && (
          <a
            href={approval.officialUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-strong underline underline-offset-4"
          >
            {tr("copy.continue_on_the_official_site_a372f3a")}<ExternalLink className="size-3.5" aria-hidden />
          </a>
        )}
      </div>
      {pending && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
          {compact ? <Link to="/documents?tab=approvals" className="inline-flex min-h-11 items-center rounded-lg border border-line-strong px-4 text-sm font-medium hover:bg-sunken">{tr("copy.review_request_525f174")}</Link> : <Button size="sm" loading={decide.isPending && decide.variables?.decision === "approve"} disabled={decide.isPending} onClick={() => run("approve")}>
            {approval.actionKind === "communication" ? tr("copy.approve_message_7f0e737") : tr("copy.approve_action_47d93f3")}
          </Button>}
          <Button size="sm" variant="ghost" disabled={decide.isPending} onClick={() => run("reject")} icon={<RotateCcw className="size-3.5" aria-hidden />}>
            {tr("copy.not_now_e457149")}</Button>
          {approval.reversible && <span className="ms-auto text-2xs text-subtle">{tr("copy.you_can_undo_this_later_1a5046a")}</span>}
        </div>
      )}
    </article>
  );
}
