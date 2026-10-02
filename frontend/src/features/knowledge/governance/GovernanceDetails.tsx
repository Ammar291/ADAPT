import { tr, localize, useLocale } from "@/i18n";
import { ChevronRight, Info, KeyRound, Quote } from "lucide-react";
import type { ReactNode } from "react";
import { SourceLink } from "@/components/ui/SourceLink";
import { ErrorState, SkeletonText } from "@/components/ui/States";
import { TrustBadge } from "@/components/ui/TrustBadge";
import type { KnowledgeNode } from "@/domain/graph";
import { useGovernanceNode } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { acronymOf, aliasesOf, describeCondition, groupNeighbours, propertyFacts, requiresUaePass, typeLabel, withoutAcronym, type ConditionText } from "./model";

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  useLocale();
  return (
    <section className={cn("border-t border-line pt-4", className)}>
      <h3 className="mb-2.5 text-sm font-medium text-ink">{localize(title)}</h3>
      {localize(children)}
    </section>
  );
}

function ConditionList({ condition, depth = 0 }: { condition: ConditionText; depth?: number }) {
  useLocale();
  if (condition.kind === "leaf") return <p className="text-sm text-ink">{localize(condition.text)}</p>;
  return (
    <div className={cn(depth > 0 && "border-s-2 border-line ps-3")}>
      <p className="text-xs text-muted">{condition.kind === "any" ? tr("copy.any_one_of_these_3cf82af") : tr("copy.all_of_these_d8aa33f")}</p>
      <ul className="mt-1.5 flex flex-col gap-1.5">
        {condition.items.map((item, i) => (
          <li key={i} className={cn(item.kind === "leaf" && "flex gap-2")}>
            {item.kind === "leaf" && <span className="mt-2 size-1 shrink-0 rounded-full bg-civic" aria-hidden />}
            <ConditionList condition={item} depth={depth + 1} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Details of one public rule: what it is, how sure we are, conditions, where to go, and what it connects to. */
export function GovernanceDetails({ node, onJump, canJump }: { node: KnowledgeNode; onJump: (id: string) => void; canJump: (id: string) => boolean }) {
  useLocale();
  const detail = useGovernanceNode(node.key);
  const evidence = node.evidence;
  const citations = evidence?.citations ?? [];
  const first = citations[0];
  const officialUrl = node.officialUrl ?? first?.url ?? null;
  const acronym = node.type === "authority" ? acronymOf(node.label) : null;
  const condition = describeCondition(node.properties.condition);
  const note = typeof node.properties.note === "string" ? node.properties.note : null;
  const aliases = aliasesOf(node);
  const facts = propertyFacts(node);
  const groups = detail.data ? groupNeighbours(node.id, detail.data.edges, detail.data.neighbours) : [];

  return (
    <div className="flex flex-col gap-4">
      {acronym && <p className="font-display text-2xl font-semibold text-civic">{localize(acronym)}</p>}

      <div className="flex flex-col gap-2">
        {evidence && (
          <div className="flex flex-wrap items-center gap-2">
            <TrustBadge kind={evidence.kind} />
            {evidence.note && <span className="text-xs text-muted">{localize(evidence.note)}</span>}
          </div>
        )}
        {node.summary ? <p className="text-sm leading-relaxed text-ink">{localize(node.summary)}</p> : <p className="text-sm text-muted">{tr("copy.no_summary_yet_the_official_source_below_has_the_4ecc57d")}</p>}
      </div>

      {requiresUaePass(node) && (
        <p className="flex items-start gap-2.5 rounded-lg bg-civic-tint px-3 py-2.5 text-sm text-ink">
          <KeyRound className="mt-0.5 size-4 shrink-0 text-civic" aria-hidden />
          <span>
            {tr("copy.requires_uae_pass_on_the_official_site_you_sign__d23ae9a")}</span>
        </p>
      )}

      {note && (
        <p className="flex items-start gap-2.5 text-sm text-muted">
          <Info className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
          {localize(note)}
        </p>
      )}

      {condition && (
        <Section title={node.type === "eligibility_rule" ? tr("copy.who_qualifies_a003ee5") : tr("copy.when_it_s_met_6d2ce91")}>
          <ConditionList condition={condition} />
        </Section>
      )}

      {(aliases.length > 0 || facts.length > 0) && (
        <dl className="flex flex-col gap-2 text-sm">
          {aliases.length > 0 && (
            <div>
              <dt className="text-xs text-muted">{tr("copy.also_called_4365b97")}</dt>
              <dd className="mt-0.5 text-ink">{localize(aliases.join(", "))}</dd>
            </div>
          )}
          {facts.map((f) => (
            <div key={f.label}>
              <dt className="text-xs text-muted">{localize(f.label)}</dt>
              <dd className="mt-0.5 text-ink">{localize(f.value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {officialUrl && (
        <Section title={tr("copy.official_page_080b13b")}>
          <SourceLink
            title={localize((node.officialUrl ? null : first?.title) || withoutAcronym(node.label))}
            url={officialUrl}
            checkedAt={first?.retrievedAt}
            className="rounded-lg border border-line px-3 py-2.5 hover:border-line-strong"
          />
          {first?.authority && node.type !== "authority" && <p className="mt-1.5 text-2xs text-muted">{tr("copy.published_by_e0a5d9b")}{localize(first.authority)}</p>}
        </Section>
      )}

      <Section title={tr("copy.how_it_connects_37e53e0")}>
        {detail.isPending && <SkeletonText lines={4} />}
        {detail.isError && <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />}
        {detail.data && groups.length === 0 && <p className="text-sm text-muted">{tr("copy.nothing_else_in_the_graph_links_to_this_yet_9a831e6")}</p>}
        {groups.length > 0 && (
          <div className="flex flex-col gap-4">
            {groups.map((group) => (
              <div key={group.title}>
                <h4 className="mb-1.5 text-xs text-muted">{localize(group.title)}</h4>
                <ul className="flex flex-col gap-1">
                  {group.items.map(({ node: other, either }) => {
                    const jumpable = canJump(other.id);
                    const body = (
                      <>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium text-ink group-hover:underline group-hover:underline-offset-4">{localize(other.label)}</span>
                          <span className="block text-2xs text-muted">{localize(typeLabel(other.type))}</span>
                        </span>
                        {either && <span className="shrink-0 rounded-full border border-line-strong px-2 text-2xs text-muted">{tr("copy.either_fa98d8d")}</span>}
                        {jumpable && <ChevronRight className="flip-rtl size-4 shrink-0 text-subtle" aria-hidden />}
                      </>
                    );
                    return (
                      <li key={other.id}>
                        {jumpable ? (
                          <button
                            type="button"
                            onClick={() => onJump(other.id)}
                            className="group flex min-h-11 w-full items-center gap-2 rounded-md px-2 py-1.5 text-start hover:bg-sunken"
                          >
                            {localize(body)}
                          </button>
                        ) : (
                          <div className="flex min-h-11 items-center gap-2 px-2 py-1.5">{localize(body)}</div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Section>

      {citations.length > 0 && (
        <Section title={citations.length === 1 ? tr("copy.source_6da13ad") : tr("copy.sources_v0_ee6ef5d", { v0: citations.length })}>
          <ul className="flex flex-col gap-3">
            {citations.map((c, i) => (
              <li key={`${c.url}-${i}`} className="rounded-lg border border-line p-3">
                {c.quote && (
                  <p className="flex gap-2 text-sm text-ink">
                    {c.excerpt !== "paraphrase" && <Quote className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />}
                    <span>{localize(c.quote)}</span>
                  </p>
                )}
                {(c.excerpt || c.effectiveDate || c.freshness) && (
                  <p className="mt-1 text-2xs text-muted">
                    {localize([c.excerpt === "paraphrase" ? tr("copy.paraphrased_passage_f08d990") : c.excerpt === "quote" ? tr("copy.quoted_passage_1b96633") : null,
                      c.effectiveDate ? `Effective ${formatDate(c.effectiveDate)}` : null,
                      c.freshness === "stale" ? tr("copy.needs_recheck_1d243a6") : c.freshness === "undated" ? tr("copy.source_date_unavailable_b8640ef") : null,
                    ].filter(Boolean).join(" · "))}
                  </p>
                )}
                <SourceLink className="mt-2" title={localize(c.title || tr("copy.official_source_71277d1"))} url={c.url || null} checkedAt={c.retrievedAt} />
                {(c.authority || c.section) && (
                  <p className="mt-1 text-2xs text-muted">{localize([c.authority, c.section ? `Section: ${c.section}` : null].filter(Boolean).join(". "))}</p>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
