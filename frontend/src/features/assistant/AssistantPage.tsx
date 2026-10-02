import { tr, localize, useLocale } from "@/i18n";
import { CheckCircle2, ExternalLink, Hand, Lock, Sparkles, Wrench } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { SourceLink } from "@/components/ui/SourceLink";
import { TrustBadge } from "@/components/ui/TrustBadge";
import { selectActions, selectCitations, selectPendingApprovals, selectRunningTool } from "@/features/voice/selectors";
import { useVoiceStore } from "@/features/voice/store";
import { useSession } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { AssistantPanel } from "./AssistantPanel";

function Section({ title, icon, count, children }: { title: string; icon: ReactNode; count?: number; children: ReactNode }) {
  useLocale();
  return (
    <section className="border-b border-line px-5 py-4 last:border-b-0">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-medium">
        <span className="text-subtle" aria-hidden>
          {localize(icon)}
        </span>
        {localize(title)}
        {count ? <span className="tabular ms-auto rounded-full bg-sunken px-2 text-2xs text-muted">{localize(count)}</span> : null}
      </h2>
      {localize(children)}
    </section>
  );
}

function Quiet({ children }: { children: ReactNode }) {
  useLocale();
  return <p className="text-sm text-subtle">{localize(children)}</p>;
}

/** What the assistant is doing and has done: the transparency column beside the conversation. */
function ActivityColumn() {
  useLocale();
  const running = useVoiceStore(selectRunningTool);
  const citations = useVoiceStore(selectCitations);
  const actions = useVoiceStore(selectActions);
  const approvals = useVoiceStore(selectPendingApprovals);

  return (
    <div className="flex flex-col">
      <Section title={tr("copy.working_on_8b8ea15")} icon={<Wrench className="size-4" />}>
        <div aria-live="polite">
          <AnimatePresence mode="wait" initial={false}>
            {running ? (
              <motion.div
                key={running.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-3 rounded-lg border border-primary/30 bg-primary-tint px-3 py-2.5"
              >
                <Spinner className="size-4 text-primary" />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-primary-strong">{localize(running.label)}</span>
                </span>
              </motion.div>
            ) : (
              <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                <Quiet>{tr("copy.ready_when_you_are_you_ll_see_progress_here_as_a_9f0075f")}</Quiet>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </Section>

      <Section title={tr("copy.waiting_for_your_approval_5095847")} icon={<Hand className="size-4" />} count={approvals.length}>
        {approvals.length ? (
          <ul className="flex flex-col gap-2">
            {approvals.map((item) => (
              <li key={item.id} className="rounded-lg border border-ink/80 px-3 py-2.5">
                <p className="text-sm font-medium">{localize(item.request.title)}</p>
                <p className="mt-0.5 text-2xs text-muted">{tr("copy.review_and_decide_in_the_conversation_d3b8157")}</p>
              </li>
            ))}
          </ul>
        ) : (
          <Quiet>{tr("copy.adapt_asks_here_before_it_sends_books_or_submits_e8d97e0")}</Quiet>
        )}
      </Section>

      <Section title={tr("copy.sources_2eb56be")} icon={<Sparkles className="size-4" />} count={citations.length}>
        {citations.length ? (
          <ul className="flex flex-col gap-3">
            {citations.slice(0, 8).map((citation) => (
              <li key={citation.url} className="flex flex-col items-start gap-1.5">
                <TrustBadge kind={citation.kind} />
                <SourceLink title={localize(citation.title)} url={citation.url} authority={citation.authority} checkedAt={citation.retrievedAt} className="w-full" />
              </li>
            ))}
          </ul>
        ) : (
          <Quiet>{tr("copy.every_answer_about_rules_links_to_the_official_p_e7fad8a")}</Quiet>
        )}
      </Section>

      <Section title={tr("copy.actions_taken_d6f8fc7")} icon={<CheckCircle2 className="size-4" />} count={actions.length}>
        {actions.length ? (
          <ol className="flex flex-col gap-2.5">
            {actions
              .slice()
              .reverse()
              .slice(0, 10)
              .map((action) => (
                <li key={action.id} className="flex items-start gap-2.5 text-sm">
                  <span
                    className={cn(
                      "mt-1.5 size-2 shrink-0 rounded-full",
                      action.status === "declined" || action.status === "error" ? "bg-line-strong" : "bg-primary",
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block">{localize(action.title)}</span>
                    {action.summary && <span className="block text-2xs text-muted">{localize(action.summary)}</span>}
                    {action.handoffUrl && (
                      <a
                        href={action.handoffUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1 inline-flex items-center gap-1 text-2xs font-medium text-primary-strong underline underline-offset-4"
                      >
                        {tr("copy.continue_on_the_official_site_a372f3a")}<ExternalLink className="size-3" aria-hidden />
                      </a>
                    )}
                  </span>
                </li>
              ))}
          </ol>
        ) : (
          <Quiet>{tr("copy.checks_adapt_ran_and_decisions_you_made_are_list_3f14d56")}</Quiet>
        )}
      </Section>
    </div>
  );
}

/** Full-screen voice and text conversation, with a transparent record of what ADAPT did. */
export default function AssistantPage() {
  useLocale();
  const session = useSession();
  const keepTranscripts = session.data?.preferences.voiceTranscriptsRetained ?? false;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 px-4 pt-4 pb-4 sm:px-6 lg:flex-row lg:gap-6 lg:px-8 lg:pt-8 lg:pb-8">
      <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">
        {/* On phones the top bar already names the page; the conversation gets the space. */}
        <header className="mb-4 hidden flex-wrap items-end justify-between gap-3 lg:flex">
          <div>
            <h1 className="text-2xl sm:text-3xl">{tr("copy.assistant_8010d1f")}</h1>
            <p className="mt-1 max-w-xl text-muted">{tr("copy.talk_or_type_in_any_language_adapt_checks_offici_303ec76")}</p>
          </div>
        </header>
        <Card
          tone="raised"
          className="flex h-[calc(100dvh-3.5rem-4rem-env(safe-area-inset-top)-env(safe-area-inset-bottom)-2rem)] min-h-[28rem] flex-col overflow-hidden lg:h-auto lg:min-h-0 lg:flex-1"
        >
          <AssistantPanel variant="page" />
        </Card>
      </div>

      <aside aria-label={tr("copy.assistant_activity_d3c6362")} className="flex flex-col gap-4 lg:w-[360px] lg:shrink-0 lg:overflow-y-auto">
        <Card tone="flat" className="overflow-hidden">
          <ActivityColumn />
        </Card>
        <p className="flex gap-2.5 px-1 text-xs text-muted">
          <Lock className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
          <span>
            {keepTranscripts
              ? tr("copy.written_transcripts_are_kept_so_you_can_review_t_ac3bbaf")
              : tr("copy.this_conversation_is_kept_only_while_this_page_i_3a83e4b")}{localize(" ")}
            <Link to="/settings" className="underline underline-offset-4 hover:text-ink">
              {tr("copy.change_in_settings_e27e5ba")}</Link>
          </span>
        </p>
      </aside>
    </div>
  );
}
