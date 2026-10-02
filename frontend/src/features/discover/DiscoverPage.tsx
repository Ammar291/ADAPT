import { tr, localize, useLocale } from "@/i18n";
/**
 * Discover: communities, places and everyday know-how for life in Abu Dhabi, found by
 * background research that never blocks the journey. Every result shows its source, how much
 * weight that source carries and when it was last checked.
 */
import { Bookmark, HandHeart, RefreshCw, SearchX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Button, buttonClass } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState, ErrorState, Skeleton, SkeletonText } from "@/components/ui/States";
import { DISCOVER_SECTIONS, type DiscoverSection } from "@/domain/discover";
import { useActiveJourney, useDiscoverActions, useDiscoverItems, useResearchStatus, useSession } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { usePrefersReducedMotion } from "@/lib/hooks/useMediaQuery";
import { DiscoverCard, type CardVariant } from "./components/DiscoverCard";
import { ResearchPanel } from "./components/ResearchPanel";
import { SectionNav } from "./components/SectionNav";
import {
  SLOT_CLASS,
  cardSlots,
  type CardSlot,
  countBySection,
  faithNeedsOptIn,
  groupBySection,
  sectionState,
  type SectionGroup,
  type SectionState,
} from "./lib/discover";

const GRID = "grid grid-cols-1 gap-4 @3xl/main:grid-cols-2 @5xl/main:grid-cols-12";

/** Short tips read better as a divided list than as a wall of cards. */
const LIST_SECTIONS: ReadonlySet<DiscoverSection> = new Set(["culture", "surprises"]);

function slotVariant(slot: CardSlot): CardVariant {
  return slot === "feature" ? "feature" : slot === "lead" ? "lead" : "standard";
}

function sectionAnchor(id: DiscoverSection) {
  return `discover-${id}`;
}

function SkeletonCards({ label }: { label?: string }) {
  useLocale();
  return (
    <div className={GRID} role="status" aria-label={localize(label ?? tr("copy.loading_results_d4b8ec0"))}>
      {cardSlots(3).map((slot, i) => (
        <div key={i} className={cn("flex flex-col rounded-xl border border-line bg-surface p-5", SLOT_CLASS[slot])}>
          <Skeleton className="h-6 w-28" />
          <Skeleton className={cn("mt-4", i === 0 ? "h-7 w-1/3" : "h-5 w-1/2")} />
          <SkeletonText lines={2} className={cn("mt-4", i === 0 && "max-w-xl")} />
          <Skeleton className="mt-6 h-8 w-40" />
        </div>
      ))}
    </div>
  );
}

function FaithInvitation() {
  useLocale();
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-dashed border-line-strong bg-surface p-5 sm:flex-row sm:items-center sm:p-6">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-sunken text-muted" aria-hidden>
        <HandHeart className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{tr("copy.would_you_like_to_see_places_of_worship_and_fait_24081b7")}</p>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          {tr("copy.adapt_never_guesses_your_faith_if_you_d_like_thi_efc061a")}</p>
      </div>
      <Link to="/settings" className={buttonClass("secondary", "md", "self-start sm:self-center")}>
        {tr("copy.open_settings_134635e")}</Link>
    </div>
  );
}

/** Before any research has run: what each section will hold, instead of seven empty boxes. */
function SectionPreview({ faithOptIn }: { faithOptIn: boolean }) {
  useLocale();
  return (
    <section aria-labelledby="discover-preview" className="mt-10">
      <h2 id="discover-preview" className="text-xl">
        {tr("copy.what_you_ll_find_here_f7d0a0e")}</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">{tr("copy.each_result_says_why_it_fits_your_move_where_it__5791614")}</p>
      <ul className="mt-5 grid gap-x-10 divide-y divide-line border-y border-line @3xl/main:grid-cols-2 @3xl/main:divide-y-0">
        {DISCOVER_SECTIONS.map((section) => (
          <li key={section.id} className="py-4 @3xl/main:border-b @3xl/main:border-line">
            <p className="font-medium">{localize(section.title)}</p>
            <p className="mt-0.5 text-sm text-muted">
              {section.id === "faith" && faithOptIn
                ? tr("copy.places_of_worship_and_faith_communities_only_if__04613d9")
                : section.description}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function QuietNote({ children, action }: { children: ReactNode; action?: ReactNode }) {
  useLocale();
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-line-strong px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-sm text-muted">{localize(children)}</p>
      {localize(action)}
    </div>
  );
}

function SectionBlock({
  group,
  state,
  onRetry,
  retrying,
}: {
  group: SectionGroup;
  state: SectionState;
  onRetry: (section: DiscoverSection) => void;
  retrying: boolean;
}) {
  useLocale();
  const headingId = `${sectionAnchor(group.id)}-title`;
  const slots = cardSlots(group.items.length);
  let content: ReactNode;
  switch (state) {
    case "loading":
      content = <SkeletonCards />;
      break;
    case "searching":
      content = <SkeletonCards label={localize(tr("copy.checking_sources_for_v0_7c18404", { v0: group.title }))} />;
      break;
    case "faith_invite":
      content = <FaithInvitation />;
      break;
    case "failed":
      content = (
        <QuietNote
          action={
            <Button size="sm" variant="secondary" loading={retrying} onClick={() => onRetry(group.id)} icon={<RefreshCw className="size-4" aria-hidden />}>
              {tr("copy.try_this_section_again_68b3037")}</Button>
          }
        >
          {tr("copy.adapt_couldn_t_check_sources_for_this_section_th_f014a31")}</QuietNote>
      );
      break;
    case "not_started":
      content = <QuietNote>{tr("copy.results_for_this_section_appear_here_once_resear_91551ef")}</QuietNote>;
      break;
    case "empty":
      content = <QuietNote>{tr("copy.nothing_found_for_this_section_yet_refresh_resea_67ea58c")}</QuietNote>;
      break;
    case "items":
      content = LIST_SECTIONS.has(group.id) ? (
        <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
          {group.items.map((item) => (
            <DiscoverCard key={item.id} item={item} variant="row" />
          ))}
        </div>
      ) : (
        <div className={GRID}>
          {group.items.map((item, i) => (
            <DiscoverCard key={item.id} item={item} variant={slotVariant(slots[i]!)} className={SLOT_CLASS[slots[i]!]} />
          ))}
        </div>
      );
      break;
  }

  return (
    <section id={sectionAnchor(group.id)} aria-labelledby={headingId} className="scroll-mt-[calc(3.5rem+env(safe-area-inset-top)+4.5rem)] lg:scroll-mt-20">
      <header className="mb-4 flex items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h2 id={headingId} className="text-xl sm:text-2xl">
            {localize(group.title)}
          </h2>
          <p className="mt-1 text-sm text-muted">
            {state === "faith_invite" ? tr("copy.places_of_worship_and_faith_communities_shown_on_eeb7a47") : group.description}
          </p>
        </div>
        {state === "items" && (
          <span className="tabular shrink-0 pb-0.5 text-xs text-subtle">{group.items.length === 1 ? tr("copy.1_result_4e63381") : tr("copy.v0_results_e80aebc", { v0: group.items.length })}</span>
        )}
      </header>
      {localize(content)}
    </section>
  );
}

export default function DiscoverPage() {
  const uiLocale = useLocale();
  const items = useDiscoverItems();
  const status = useResearchStatus();
  const session = useSession();
  const journey = useActiveJourney();
  const { start, markSeen } = useDiscoverActions();
  const reduceMotion = usePrefersReducedMotion();
  const [savedOnly, setSavedOnly] = useState(false);
  const [active, setActive] = useState<DiscoverSection | null>(null);
  const seenJob = useRef<string | null>(null);

  // Opening Discover counts as reading the Life Brief.
  const research = status.data;
  useEffect(() => {
    if (!research?.briefReady || research.seen || !research.jobId || seenJob.current === research.jobId) return;
    seenJob.current = research.jobId;
    markSeen.mutate(research.jobId);
  }, [research, markSeen]);

  const all = useMemo(() => items.data ?? [], [items.data, uiLocale]);
  const faithOptIn = faithNeedsOptIn(research, session.data?.preferences.faithPersonalization);
  const groups = useMemo(() => groupBySection(all, { savedOnly }), [all, savedOnly, uiLocale]);
  const counts = useMemo(() => countBySection(savedOnly ? all.filter((i) => i.saved) : all), [all, savedOnly, uiLocale]);
  const savedCount = all.filter((i) => i.saved).length;

  const states = groups.map((group) =>
    sectionState({ section: group.id, items: group.items, status: research, loading: items.isPending, faithOptIn: faithOptIn && !savedOnly, savedOnly }),
  );
  const visible = groups.filter((_group, i) => !savedOnly || states[i] === "items");
  const visibleKey = visible.map((g) => g.id).join(",");

  // Highlight the section being read in the sticky chips.
  useEffect(() => {
    const elements = visibleKey
      .split(",")
      .map((id) => document.getElementById(sectionAnchor(id as DiscoverSection)))
      .filter((el): el is HTMLElement => Boolean(el));
    if (!elements.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.id.replace("discover-", "") as DiscoverSection);
      },
      { rootMargin: "-140px 0px -55% 0px" },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [visibleKey]);

  const jump = useCallback(
    (id: DiscoverSection) => {
      setActive(id);
      document.getElementById(sectionAnchor(id))?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    },
    [reduceMotion, uiLocale],
  );

  const startResearch = (sections?: DiscoverSection[]) => start.mutate(sections);
  const hasPlan = journey.isPending ? undefined : Boolean(journey.data);
  const nothingYet = !items.isPending && !items.isError && all.length === 0 && (hasPlan === false || !research || research.state === "idle");

  return (
    <div className="flex flex-col">
      <PageHeader title={tr("copy.discover_4827ea2")} description={tr("copy.communities_places_and_everyday_know_how_for_lif_b0adbca")} />

      <ResearchPanel
        status={research}
        statusPending={status.isPending}
        statusError={status.isError ? status.error : null}
        hasPlan={hasPlan}
        onStart={() => startResearch()}
        starting={start.isPending && !start.variables?.length}
        startError={start.error}
      />

      {nothingYet ? (
        <SectionPreview faithOptIn={faithOptIn} />
      ) : (
        <div className="mt-8">
          <SectionNav
            sections={visible.map(({ id, title }) => ({ id, title }))}
            counts={counts}
            active={active ?? visible[0]?.id ?? null}
            savedOnly={savedOnly}
            savedCount={savedCount}
            onSavedOnly={(value) => {
              setSavedOnly(value);
              setActive(null);
            }}
            onJump={jump}
          />
          <div className="mt-8 flex flex-col gap-14">
            {items.isError ? (
              <ErrorState error={items.error} onRetry={() => void items.refetch()} />
            ) : savedOnly && visible.length === 0 ? (
              <EmptyState
                icon={<Bookmark className="size-5" aria-hidden />}
                title={tr("copy.nothing_saved_yet_b54a538")}
                description={tr("copy.save_results_you_want_to_come_back_to_they_stay__b5220c4")}
                action={
                  <Button variant="secondary" onClick={() => setSavedOnly(false)}>
                    {tr("copy.show_all_results_dd0a5bf")}</Button>
                }
              />
            ) : !savedOnly && !items.isPending && all.length === 0 && research?.state === "ready" ? (
              <EmptyState
                icon={<SearchX className="size-5" aria-hidden />}
                title={tr("copy.research_didn_t_find_anything_this_time_90779f7")}
                description={tr("copy.refresh_in_a_little_while_adapt_only_shows_resul_4160efd")}
              />
            ) : (
              groups.map((group, i) =>
                visible.includes(group) ? (
                  <SectionBlock
                    key={group.id}
                    group={group}
                    state={states[i]!}
                    onRetry={(section) => startResearch([section])}
                    retrying={start.isPending && Boolean(start.variables?.length)}
                  />
                ) : null,
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
