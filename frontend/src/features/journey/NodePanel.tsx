import { tr, localize, useLocale } from "@/i18n";
/**
 * Details of one journey step: what it is, why it matters, what's in the way, what it needs
 * and unlocks, how sure ADAPT is, and the one thing to do next. A panel beside the map on
 * desktop, a sheet on phones.
 */
import { ArrowUpRight, CalendarClock, Check, KeyRound, Landmark, MessageCircleQuestion, Timer, TriangleAlert, Waypoints, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { NodeActionButton, needsUaePassNote } from "@/components/journey/NodeActionButton";
import { AreaLabel } from "@/components/ui/AreaLabel";
import { Button, IconButton } from "@/components/ui/Button";
import { Field, TextArea } from "@/components/ui/Field";
import { Sheet } from "@/components/ui/Sheet";
import { SourceLink } from "@/components/ui/SourceLink";
import { Skeleton } from "@/components/ui/States";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { TrustBadge } from "@/components/ui/TrustBadge";
import type { Journey, JourneyNode } from "@/domain/journey";
import { useAnswerNode, useApprovals, useMarkNodeDone } from "@/lib/api/hooks";
import { describeError } from "@/lib/api/errors";
import { STATUS_LABEL, criticalPath, nodeByKey, prerequisites, unlocks } from "@/lib/journey/analysis";
import { cn } from "@/lib/cn";
import { daysUntil, dueLabel, formatDate } from "@/lib/format";
import { useUiStore } from "@/stores/ui";
import { KIND_ICON, KIND_LABEL, StatusGlyph } from "./visuals";

export const PANEL_WIDTH = 420;

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  useLocale();
  return (
    <section className={cn("border-t border-line py-5", className)}>
      <h3 className="mb-2.5 text-sm font-medium text-ink">{localize(title)}</h3>
      {localize(children)}
    </section>
  );
}

/** A linked step, shown as a row that focuses it on the map. */
function StepLink({ node, onSelect, meta }: { node: JourneyNode; onSelect: (key: string) => void; meta?: ReactNode }) {
  useLocale();
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.key)}
        className="group flex min-h-11 w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-start hover:bg-sunken"
      >
        <StatusGlyph status={node.status} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm text-ink group-hover:underline group-hover:underline-offset-4">{localize(node.title)}</span>
          <span className="block text-2xs text-subtle">{localize(meta ?? STATUS_LABEL[node.status])}</span>
        </span>
        <ArrowUpRight className="flip-rtl size-4 shrink-0 text-subtle" aria-hidden />
      </button>
    </li>
  );
}

function AnswerForm({ journey, node, onDone }: { journey: Journey; node: JourneyNode; onDone: () => void }) {
  useLocale();
  const answer = useAnswerNode();
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const blocker = node.blockers.find((b) => b.relatedNodeKey === null) ?? node.blockers[0];
  const question = node.action?.question || blocker?.message || tr("copy.your_answer_3ae5ff6");
  const failure = answer.error ? describeError(answer.error) : null;
  useEffect(() => ref.current?.focus({ preventScroll: true }), []);

  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-3.5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!value.trim()) return;
        answer.mutate([journey.id, node.key, value.trim()], {
          onSuccess: () => {
            toast({ title: tr("copy.answer_saved_b5b1762"), description: tr("copy.adapt_updated_your_plan__ac50bf8") });
            onDone();
          },
        });
      }}
    >
      <Field
        label={localize(question)}
        hint={localize(blocker?.resolution ?? tr("copy.only_used_to_plan_this_step_417f85d"))}
        error={failure ? failure.detail || failure.title : null}
      >
        {localize((props) => (
          <TextArea
            ref={ref}
            {...props}
            rows={3}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              if (answer.isError) answer.reset();
            }}
          />
        ))}
      </Field>
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" loading={answer.isPending} disabled={!value.trim()}>
          {tr("copy.save_answer_5ef20e0")}</Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          {tr("copy.cancel_77dfd21")}</Button>
      </div>
    </form>
  );
}

const USER_COMPLETABLE = new Set(["todo", "in_progress", "prepared"]);

function NextMove({ journey, node }: { journey: Journey; node: JourneyNode }) {
  useLocale();
  const approvals = useApprovals();
  const markDone = useMarkNodeDone();
  const openAssistant = useUiStore((s) => s.setAssistantOpen);
  const [answering, setAnswering] = useState(false);
  const action = node.action;
  const approvalId = action?.approvalId ?? null;
  const approval = approvalId ? approvals.data?.find((a) => a.id === approvalId) : undefined;
  const pendingApproval = approval?.status === "pending";
  const isApprovalNode = node.kind === "approval";
  const showButton = !isApprovalNode && !pendingApproval && !answering;
  const canMarkDone =
    !node.officialUrl &&
    !node.governanceKey?.startsWith("service.") &&
    node.kind === "task" &&
    USER_COMPLETABLE.has(node.status) &&
    action?.kind !== "mark_done" &&
    action?.kind !== "answer_question";

  return (
    <div className="flex flex-col gap-3">
      {approvalId && approvals.isPending && <Skeleton className="h-40 w-full rounded-xl" />}
      {approval && <ApprovalCard approval={approval} />}
      {answering && <AnswerForm journey={journey} node={node} onDone={() => setAnswering(false)} />}
      {(showButton || canMarkDone) && (
        <div className="flex flex-wrap items-center gap-2">
          {showButton && <NodeActionButton node={node} journeyId={journey.id} onAnswer={() => setAnswering(true)} />}
          {canMarkDone && (
            <Button
              variant="secondary"
              loading={markDone.isPending}
              icon={<Check className="size-4" aria-hidden />}
              onClick={() =>
                markDone.mutate([journey.id, node.key], {
                  onSuccess: () => toast({ title: tr("copy.marked_as_done_06dcd52"), description: node.title }),
                  onError: (error) => toast({ title: describeError(error).title, tone: "error" }),
                })
              }
            >
              {tr("copy.mark_as_done_bdf91e4")}</Button>
          )}
        </div>
      )}
      {needsUaePassNote(node) && action?.kind === "official_handoff" && (
        <p className="flex items-start gap-2 text-xs text-muted">
          <KeyRound className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
          {tr("copy.you_sign_in_with_uae_pass_on_the_official_site_a_295d4cd")}</p>
      )}
      <button
        type="button"
        onClick={() => openAssistant(true)}
        className="inline-flex min-h-10 items-center gap-2 self-start rounded-md text-sm font-medium text-primary-strong hover:underline hover:underline-offset-4"
      >
        <MessageCircleQuestion className="size-4" aria-hidden />
        {tr("copy.ask_adapt_about_this_42f3929")}</button>
    </div>
  );
}

/** Everything about a step except its title block (the sheet renders its own). */
export function NodeDetails({ journey, node, onSelect }: { journey: Journey; node: JourneyNode; onSelect: (key: string) => void }) {
  useLocale();
  const prereqs = prerequisites(journey, node.key);
  const unlocked = unlocks(journey, node.key);
  const onCritical = criticalPath(journey).includes(node.key);
  const due = node.dueBy ? daysUntil(node.dueBy) : null;
  const citations = node.evidence.citations;
  const officialListed = node.officialUrl && citations.some((c) => c.url === node.officialUrl);

  return (
    // `relative` keeps screen-reader-only text positioned inside the scrolling body (inside a
    // native <dialog> it would otherwise stretch the dialog itself and scroll it).
    <div className="relative flex flex-col">
      <p className="pb-5 text-base text-muted">{localize(node.summary)}</p>

      {node.status !== "done" && node.status !== "not_applicable" && (
        <div className="pb-5">
          <NextMove journey={journey} node={node} />
        </div>
      )}

      {(node.whyItMatters || unlocked.length > 0 || onCritical || node.estimatedDays || node.dueBy || node.completedAt) && (
        <Section title={tr("copy.why_it_matters_750c209")}>
          {node.whyItMatters && <p className="text-sm">{localize(node.whyItMatters)}</p>}
          {onCritical && (
            <p className="mt-3 flex items-start gap-2 rounded-md border-s-2 border-primary bg-primary-tint/60 px-3 py-2 text-sm text-ink">
              <Waypoints className="mt-0.5 size-4 shrink-0 text-primary-strong" aria-hidden />
              {tr("copy.this_step_is_on_your_critical_path_delaying_it_d_1e4753e")}</p>
          )}
          <dl className="mt-3 flex flex-col gap-2 text-sm">
            {node.estimatedDays !== null && node.estimatedDays > 0 && (
              <div className="flex items-start gap-2">
                <dt className="sr-only">{tr("copy.estimated_time_85f38b2")}</dt>
                <Timer className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
                <dd>
                  {tr("copy.about_dae445c")}{localize(node.estimatedDays)} {node.estimatedDays === 1 ? tr("copy.day_a2620cb") : tr("copy.days_5548ae4")}
                  <span className="block text-2xs text-subtle">{tr("copy.adapt_estimate_not_an_official_processing_time_803be53")}</span>
                </dd>
              </div>
            )}
            {node.dueBy && node.status !== "done" && (
              <div className="flex items-start gap-2">
                <dt className="sr-only">{tr("copy.target_date_e337ddc")}</dt>
                <CalendarClock className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
                <dd className={cn(due !== null && due < 0 && "text-danger")}>
                  {tr("copy.aim_for_be2f36b")}{localize(formatDate(node.dueBy))} {tr("copy.text_28ed3a7")}{localize(dueLabel(node.dueBy))}{tr("copy.text_e7064f0")}</dd>
              </div>
            )}
            {node.completedAt && node.status === "done" && (
              <div className="flex items-start gap-2">
                <dt className="sr-only">{tr("copy.completed_1798b3b")}</dt>
                <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                <dd>{tr("copy.completed_64f7bf2")}{localize(formatDate(node.completedAt))}</dd>
              </div>
            )}
          </dl>
          {unlocked.length > 0 && (
            <>
              <p className="mt-4 mb-1 text-xs font-medium text-muted">{tr("copy.unlocks_aecf18a")}</p>
              <ul className="-mx-2 flex flex-col">
                {unlocked.map((n) => (
                  <StepLink key={n.key} node={n} onSelect={onSelect} />
                ))}
              </ul>
            </>
          )}
        </Section>
      )}

      {node.blockers.length > 0 && (
        <Section title={node.status === "blocked" ? tr("copy.what_s_in_the_way_ac8015f") : tr("copy.what_adapt_needs_from_you_637daec")}>
          <ul className="flex flex-col gap-3">
            {node.blockers.map((blocker, index) => {
              const related = blocker.relatedNodeKey ? nodeByKey(journey, blocker.relatedNodeKey) : undefined;
              return (
                <li key={`${blocker.kind}-${index}`} className="rounded-lg border border-line bg-muted-surface p-3">
                  <p className="flex items-start gap-2 text-sm font-medium">
                    <TriangleAlert className={cn("mt-0.5 size-4 shrink-0", node.status === "blocked" ? "text-danger" : "text-muted")} aria-hidden />
                    {localize(blocker.message)}
                  </p>
                  {blocker.resolution && blocker.resolution !== related?.action?.label && <p className="mt-1 ps-6 text-sm text-muted">{localize(blocker.resolution)}</p>}
                  {related && (
                    <button
                      type="button"
                      onClick={() => onSelect(related.key)}
                      className="mt-2 ms-6 inline-flex min-h-8 items-center gap-1 text-sm font-medium text-primary-strong hover:underline hover:underline-offset-4"
                    >
                      {tr("copy.go_to_b49acb6")}{localize(related.title)}
                      <ArrowUpRight className="flip-rtl size-3.5" aria-hidden />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {prereqs.length > 0 && (
        <Section title={tr("copy.needs_first_c158e64")}>
          <ul className="-mx-2 flex flex-col">
            {prereqs.map(({ node: pre, edge }) => (
              <StepLink
                key={edge.id}
                node={pre}
                onSelect={onSelect}
                meta={`${STATUS_LABEL[pre.status]}${edge.relation === "requires" ? tr("copy._required_2e5396f") : ""}${edge.anyOf ? tr("copy._either_of_these_1a4d09b") : ""}`}
              />
            ))}
          </ul>
        </Section>
      )}

      <Section title={tr("copy.how_sure_this_is_2b461f6")}>
        <div className="flex flex-wrap items-center gap-2">
          <TrustBadge kind={node.evidence.kind} />
          {node.evidence.confidence !== null && (
            <span className="tabular text-xs text-muted">{tr("copy.confidence_fa7a93e")}{localize(Math.round(node.evidence.confidence * 100))}{tr("copy.text_4345cb1")}</span>
          )}
        </div>
        {node.evidence.note && <p className="mt-2 text-sm text-muted">{localize(node.evidence.note)}</p>}
      </Section>

      {(citations.length > 0 || node.officialUrl || node.governanceKey) && (
        <Section title={tr("copy.sources_2eb56be")}>
          <ul className="flex flex-col gap-4">
            {node.officialUrl && !officialListed && (
              <li>
                <SourceLink title={localize(node.authority ?? tr("copy.official_page_080b13b"))} authority={node.authority} url={node.officialUrl} />
              </li>
            )}
            {citations.map((citation) => (
              <li key={`${citation.url}-${citation.section ?? ""}`}>
                <SourceLink title={localize(citation.title)} authority={citation.authority} url={citation.url} checkedAt={citation.retrievedAt} />
                {citation.section && <p className="mt-1 text-2xs text-subtle">{localize(citation.section)}</p>}
                {citation.quote && (
                  <blockquote className="mt-2 border-s-2 border-civic/50 ps-3 text-sm text-muted">{"?"}{localize(citation.quote)}{"?"}</blockquote>
                )}
              </li>
            ))}
          </ul>
          {node.governanceKey && (
            <Link
              to={`/knowledge/governance?node=${encodeURIComponent(node.governanceKey)}`}
              className="mt-4 inline-flex min-h-10 items-center gap-2 text-sm font-medium text-civic hover:underline hover:underline-offset-4"
            >
              <Landmark className="size-4" aria-hidden />
              {tr("copy.see_the_official_rule_behind_this_78a2dc5")}</Link>
          )}
        </Section>
      )}
    </div>
  );
}

function KindLine({ node }: { node: JourneyNode }) {
  useLocale();
  const Icon = KIND_ICON[node.kind];
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <span className="inline-flex items-center gap-1.5">
        <Icon className="size-3.5" aria-hidden />
        {localize(KIND_LABEL[node.kind])}
      </span>
      <AreaLabel area={node.area} className="text-xs" />
    </span>
  );
}

/** Desktop: a panel that slides in beside the map. */
export function DesktopNodePanel({
  journey,
  node,
  onSelect,
  onClose,
}: {
  journey: Journey;
  node: JourneyNode | null;
  onSelect: (key: string) => void;
  onClose: () => void;
}) {
  useLocale();
  const reduceMotion = useReducedMotion();
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const key = node?.key;

  useEffect(() => {
    if (!key) return;
    scroller.current?.scrollTo({ top: 0 });
    heading.current?.focus({ preventScroll: true });
  }, [key]);

  return (
    <AnimatePresence initial={false}>
      {node && (
        <motion.aside
          key="panel"
          aria-labelledby={titleId}
          initial={reduceMotion ? { opacity: 0 } : { width: 0, opacity: 0 }}
          animate={reduceMotion ? { opacity: 1 } : { width: PANEL_WIDTH, opacity: 1 }}
          exit={reduceMotion ? { opacity: 0 } : { width: 0, opacity: 0 }}
          transition={{ duration: 0.26, ease: [0.2, 0, 0, 1] }}
          data-journey-panel
          className={cn(
            // Docked beside the map when the page is wide; over the map's end when it isn't
            // (e.g. with the assistant docked on a laptop).
            "absolute inset-y-0 end-0 z-20 max-w-full shrink-0 overflow-hidden border-s border-line bg-surface shadow-overlay",
            "@5xl/main:relative @5xl/main:inset-auto @5xl/main:z-10 @5xl/main:shadow-raised",
          )}
          style={reduceMotion ? { width: PANEL_WIDTH } : undefined}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              onClose();
            }
          }}
        >
          <div className="flex h-full flex-col" style={{ width: PANEL_WIDTH }}>
            <header className="border-b border-line px-5 pt-4 pb-4">
              <div className="flex items-start justify-between gap-3">
                <KindLine node={node} />
                <IconButton label={tr("copy.close_details_433da6d")} size="sm" onClick={onClose} className="-me-2 -mt-1.5">
                  <X className="size-5" aria-hidden />
                </IconButton>
              </div>
              <motion.div key={node.key} initial={reduceMotion ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
                <h2 id={titleId} ref={heading} tabIndex={-1} className="mt-2 text-xl leading-snug focus:outline-none">
                  {localize(node.title)}
                </h2>
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  <StatusBadge status={node.status} />
                </div>
              </motion.div>
            </header>
            {/* Bottom room so the last section can scroll clear of the floating assistant button. */}
            <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-5 pt-4 pb-28">
              <NodeDetails key={node.key} journey={journey} node={node} onSelect={onSelect} />
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

/** Phones and tablets: the same details in a sheet. */
export function MobileNodeSheet({
  journey,
  node,
  onSelect,
  onClose,
}: {
  journey: Journey;
  node: JourneyNode | null;
  onSelect: (key: string) => void;
  onClose: () => void;
}) {
  useLocale();
  // Keep the last node while the sheet animates closed.
  const [shown, setShown] = useState(node);
  useEffect(() => {
    if (node) setShown(node);
  }, [node]);
  return (
    <Sheet
      open={Boolean(node)}
      onClose={onClose}
      title={localize(shown?.title ?? tr("copy.step_details_ffa8d71"))}
      tall
      description={
        shown ? (
          <span className="mt-1.5 flex flex-wrap items-center gap-2">
            <StatusBadge status={shown.status} />
            <KindLine node={shown} />
          </span>
        ) : undefined
      }
    >
      {shown && <NodeDetails key={shown.key} journey={journey} node={shown} onSelect={onSelect} />}
    </Sheet>
  );
}

