import { tr, localize, useLocale } from "@/i18n";
import { CheckCircle2, ChevronRight, CircleAlert, Eye, EyeOff, Landmark, Lock } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { TrustBadge } from "@/components/ui/TrustBadge";
import type { KnowledgeGraph, KnowledgeNode } from "@/domain/graph";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { factRows, maskValue, type FactRow } from "./facts";
import { twinConnections, twinTypeLabel } from "./model";

function FactItem({ row }: { row: FactRow }) {
  useLocale();
  const [shown, setShown] = useState(false);
  const hidden = row.sensitive && !shown;
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-muted">{localize(row.label)}</p>
          <p className={cn("mt-0.5 text-sm font-medium text-ink", (hidden || row.masked) && "tabular tracking-wide")}>
            {hidden ? maskValue(row.value) : row.value}
          </p>
        </div>
        {row.sensitive && (
          <button
            type="button"
            aria-pressed={shown}
            onClick={() => setShown((s) => !s)}
            className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-muted hover:bg-sunken hover:text-ink"
          >
            {shown ? <EyeOff className="size-3.5" aria-hidden /> : <Eye className="size-3.5" aria-hidden />}
            {shown ? tr("copy.hide_34d8b60") : tr("copy.show_d97d1ee")}
            <span className="sr-only">{localize(row.label)}</span>
          </button>
        )}
      </div>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
        <span>{localize(row.source)}</span>
        <span className={cn(row.confidenceLevel === "low" && "text-danger")}>{localize(row.confidence)}</span>
        {row.confirmed ? (
          <span className="inline-flex items-center gap-1 text-primary-strong">
            <CheckCircle2 className="size-3" aria-hidden />
            {tr("copy.confirmed_by_you_1b733cf")}</span>
        ) : (
          <span className="inline-flex items-center gap-1 text-ink">
            <CircleAlert className="size-3 text-primary" aria-hidden />
            {tr("copy.needs_your_review_29dac63")}</span>
        )}
        {row.observedAt && <span>{tr("copy.noted_6689380")}{localize(formatDate(row.observedAt))}</span>}
      </p>
    </li>
  );
}

/** Details of one twin node: its private facts with provenance, or a linked public rule. */
export function TwinDetails({ node, graph, onJump }: { node: KnowledgeNode; graph: KnowledgeGraph; onJump: (id: string) => void }) {
  useLocale();
  const isPublic = node.scope === "governance";
  const rows = factRows(node.facts);
  const connections = twinConnections(node.id, graph);
  const needsReview = rows.some((r) => !r.confirmed);

  return (
    <div className="flex flex-col gap-5">
      {isPublic ? (
        <div className="flex flex-col gap-3">
          <p className="flex items-center gap-2 text-xs text-civic">
            <Landmark className="size-3.5" aria-hidden />
            {tr("copy.shared_public_rule_the_same_for_everyone_your_tw_b89cd66")}</p>
          {node.evidence && <TrustBadge kind={node.evidence.kind} className="self-start" />}
          <p className="text-sm leading-relaxed text-ink">{localize(node.summary ?? tr("copy.the_governance_graph_has_the_full_details_and_of_4d13e9a"))}</p>
          <Link to={`/knowledge/governance?node=${encodeURIComponent(node.key)}`} className={buttonClass("secondary", "md", "self-start")}>
            {tr("copy.open_in_the_governance_graph_9d8eb48")}</Link>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="primary" icon={<Lock className="size-3" aria-hidden />}>
            {tr("copy.private_to_you_c1b4514")}</Badge>
          {node.summary && <span className="text-xs text-muted">{localize(node.summary)}</span>}
        </div>
      )}

      {!isPublic && (
        <section aria-labelledby={`facts-${node.id}`}>
          <div className="mb-2.5 flex items-baseline justify-between gap-3">
            <h3 id={`facts-${node.id}`} className="text-sm font-medium">
              {tr("copy.what_adapt_knows_859d76a")}</h3>
            {needsReview && node.type === "document" && (
              <Link to="/documents" className="text-xs font-medium text-primary-strong hover:underline">
                {tr("copy.review_in_documents_94b51aa")}</Link>
            )}
          </div>
          {rows.length === 0 ? (
            <p className="text-sm text-muted">
              {tr("copy.no_details_stored_for_this_303d152")}{localize(twinTypeLabel(node).toLowerCase())} {tr("copy.yet_they_appear_as_you_tell_adapt_about_your_mov_9c46e0a")}</p>
          ) : (
            <ul className="divide-y divide-line rounded-lg border border-line bg-surface px-3.5 py-3">
              {rows.map((row) => (
                <FactItem key={row.key} row={row} />
              ))}
            </ul>
          )}
        </section>
      )}

      {connections.length > 0 && (
        <section className="border-t border-line pt-4">
          <h3 className="mb-2.5 text-sm font-medium">{tr("copy.connections_8f3509b")}</h3>
          <div className="flex flex-col gap-4">
            {connections.map((group) => (
              <div key={group.title}>
                <h4 className="mb-1.5 text-xs text-muted">{localize(group.title)}</h4>
                <ul className="flex flex-col gap-1">
                  {group.items.map(({ node: other, isPublic: otherPublic, relation }) => (
                    <li key={other.id}>
                      <button
                        type="button"
                        onClick={() => onJump(other.id)}
                        className="group flex min-h-11 w-full items-center gap-2 rounded-md px-2 py-1.5 text-start hover:bg-sunken"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium text-ink group-hover:underline group-hover:underline-offset-4">{localize(other.label)}</span>
                          <span className={cn("block text-2xs", otherPublic ? "text-civic" : "text-muted")}>{otherPublic ? tr("copy.public_rule_2878b51") : tr("copy.yours_755844b")}</span>
                        </span>
                        {relation === "blocked_by" && <span className="shrink-0 rounded-full bg-danger-tint px-2 text-2xs text-danger">{tr("copy.blocking_d785c0d")}</span>}
                        <ChevronRight className="flip-rtl size-4 shrink-0 text-subtle" aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
