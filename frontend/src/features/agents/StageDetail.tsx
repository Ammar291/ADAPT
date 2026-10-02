import { tr, localize, useLocale } from "@/i18n";
import { CircleCheck, CircleX, FileText, Hand, Package, X } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { IconButton } from "@/components/ui/Button";
import { SourceLink } from "@/components/ui/SourceLink";
import { TrustBadge } from "@/components/ui/TrustBadge";
import { ACTION_KIND_LABEL, type ActionKind } from "@/domain/common";
import type { AgentStage } from "@/domain/runs";
import type { StageStatus, StageView } from "@/lib/events/runEvents";
import { cn } from "@/lib/cn";
import { formatDuration, formatTime } from "@/lib/format";
import { artifactLink, formatArgs, type StageActivity } from "./log";
import { KindIcon, LiveDot, STAGE_STATUS, StagePill } from "./StageStatus";

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  useLocale();
  return (
    <section className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 font-sans text-sm font-medium text-ink">
        {localize(title)}
        {count !== undefined && <span className="tabular rounded-full bg-sunken px-1.5 text-2xs text-muted">{localize(count)}</span>}
      </h3>
      {localize(children)}
    </section>
  );
}

function ToolStatus({ status }: { status: "running" | "done" | "failed" }) {
  useLocale();
  if (status === "running")
    return (
      <span className="inline-flex items-center gap-1 text-2xs font-medium text-primary-strong">
        <LiveDot />
        {tr("copy.running_73989d9")}</span>
    );
  if (status === "failed")
    return (
      <span className="inline-flex items-center gap-1 text-2xs font-medium text-danger">
        <CircleX className="size-3.5" aria-hidden />
        {tr("copy.failed_09fef5d")}</span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-2xs font-medium text-primary-strong">
      <CircleCheck className="size-3.5" aria-hidden />
      {tr("copy.done_e9b450d")}</span>
  );
}

/** Everything one stage did: its result, tool calls, sources found and what it produced. */
export function StageDetail({
  stage,
  view,
  status,
  activity,
  onClose,
  onGoToReview,
  headingLevel = "h2",
  className,
}: {
  stage: AgentStage;
  view: StageView | undefined;
  status: StageStatus;
  activity: StageActivity;
  onClose?: () => void;
  onGoToReview?: () => void;
  headingLevel?: "h2" | "h3";
  className?: string;
}) {
  useLocale();
  const Heading = headingLevel;
  // Inline (expanded under its row in the step list), the row already shows the name, status and result.
  const inline = !onClose;
  const text = status === "complete" ? view?.summary : view?.message;
  const nothingYet = !view?.tools.length && !activity.sources.length && !activity.documents.length && !activity.actions.length && !activity.artifacts.length;

  return (
    <div className={cn("flex flex-col gap-5", className)}>
      {inline ? (
        <p className="text-sm text-muted">{localize(stage.description)}</p>
      ) : (
        <header className="flex items-start gap-3">
          <KindIcon kind={stage.kind} className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <Heading className="text-lg leading-snug">{localize(stage.label)}</Heading>
            <p className="mt-0.5 text-sm text-muted">{localize(stage.description)}</p>
          </div>
          {onClose && (
            <IconButton label={tr("copy.close_step_details_53b4e33")} size="sm" onClick={onClose}>
              <X className="size-4" aria-hidden />
            </IconButton>
          )}
        </header>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted empty:hidden">
        {!inline && <StagePill status={status} />}
        {view?.startedAt && <span className="tabular">{tr("copy.started_750fe42")}{localize(formatTime(view.startedAt))}</span>}
        {!!view?.durationMs && <span className="tabular">{tr("copy.took_da3b7b6")}{localize(formatDuration(view.durationMs))}</span>}
        {(view?.attempt ?? 1) > 1 && <span>{tr("copy.attempt_b859b53")}{localize(view!.attempt)}</span>}
      </div>

      {status === "awaiting" ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-ink/70 p-4">
          <p className="flex items-start gap-2 text-sm">
            <Hand className="mt-0.5 size-4 shrink-0" aria-hidden />
            {tr("copy.adapt_paused_here_nothing_is_sent_booked_or_subm_2092bbb")}</p>
          {onGoToReview && (
            <button type="button" onClick={onGoToReview} className="text-sm font-medium text-primary-strong underline underline-offset-4">
              {tr("copy.go_to_your_review_4772aa3")}</button>
          )}
        </div>
      ) : inline ? null : text ? (
        <p className={cn("rounded-lg px-3 py-2.5 text-sm", status === "failed" ? "bg-danger-tint text-ink" : "bg-sunken")}>{localize(text)}</p>
      ) : (
        <p className="text-sm text-subtle">{localize(STAGE_STATUS[status].hint)}{tr("copy.text_3a52ce7")}</p>
      )}

      {view && view.tools.length > 0 && (
        <Section title={tr("copy.tool_calls_46de02c")} count={view.tools.length}>
          <ol className="flex flex-col divide-y divide-line rounded-lg border border-line">
            {view.tools.map((tool) => {
              const args = formatArgs(tool.args, 120);
              return (
                <li key={tool.callId} className="flex flex-col gap-1 px-3 py-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-sm font-medium">{localize(tool.label)}</span>
                    <ToolStatus status={tool.status} />
                  </div>
                  <p className="text-2xs text-subtle">
                    {tr("copy.tool_22379bc")}{localize(tool.tool)}
                    {args ? tr("copy.with_v0_a0b5a8c", { v0: args }) : ""}
                  </p>
                  {tool.summary && <p className={cn("text-sm", tool.status === "failed" ? "text-danger" : "text-muted")}>{localize(tool.summary)}</p>}
                </li>
              );
            })}
          </ol>
        </Section>
      )}

      {activity.sources.length > 0 && (
        <Section title={tr("copy.sources_found_f4d919d")} count={activity.sources.length}>
          <ul className="flex flex-col divide-y divide-line rounded-lg border border-line">
            {activity.sources.map((source) => (
              <li key={source.key} className="flex flex-col gap-1.5 px-3 py-2.5">
                <TrustBadge kind={source.kind} className="self-start" />
                <SourceLink title={localize(source.title)} url={source.url} authority={source.authority} checkedAt={source.checkedAt} />
                {source.authority && source.authority !== source.title && <p className="text-2xs text-muted">{localize(source.title)}</p>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {activity.documents.length > 0 && (
        <Section title={tr("copy.documents_drafted_8c8e0bf")} count={activity.documents.length}>
          <ul className="flex flex-col gap-1.5">
            {activity.documents.map((doc) => (
              <li key={doc.id} className="flex items-center gap-2 text-sm">
                <FileText className="size-4 shrink-0 text-subtle" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{localize(doc.title)}</span>
              </li>
            ))}
          </ul>
          <Link to="/documents?tab=drafts" className="self-start text-sm font-medium text-primary-strong underline-offset-4 hover:underline">
            {tr("copy.review_drafts_in_documents_d725920")}</Link>
        </Section>
      )}

      {activity.actions.length > 0 && (
        <Section title={tr("copy.actions_prepared_94bb7c8")} count={activity.actions.length}>
          <ul className="flex flex-col gap-1.5">
            {activity.actions.map((action) => (
              <li key={action.id} className="flex items-start gap-2 text-sm">
                <Package className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
                <span className="min-w-0 flex-1">
                  {localize(action.title)}
                  <span className="block text-2xs text-subtle">{localize(ACTION_KIND_LABEL[action.kind as ActionKind] ?? action.kind)}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="text-2xs text-subtle">{tr("copy.prepared_not_carried_out_you_finish_official_ste_198dd55")}</p>
        </Section>
      )}

      {activity.artifacts.length > 0 && (
        <Section title={tr("copy.created_accf40c")}>
          <ul className="flex flex-col gap-1.5">
            {activity.artifacts.map((artifact) => {
              const link = artifactLink(artifact.type);
              return (
                <li key={artifact.id} className="text-sm">
                  {link ? (
                    <Link to={link.to} className="font-medium text-primary-strong underline-offset-4 hover:underline">
                      {localize(artifact.title ?? link.label)}
                    </Link>
                  ) : (
                    (artifact.title ?? artifact.type)
                  )}
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {nothingYet && status !== "awaiting" && (
        <p className="text-sm text-subtle">
          {status === "queued"
            ? tr("copy.tool_calls_sources_and_drafts_from_this_step_app_c52d09e")
            : tr("copy.this_step_didn_t_call_tools_or_produce_anything__836e05a")}
        </p>
      )}
    </div>
  );
}
