import { tr, localize, useLocale } from "@/i18n";
import { ChevronRight, CircleUserRound, FileText, LockKeyhole, Network, PlaneLanding, ShieldCheck, SlidersHorizontal, Smartphone, Wrench, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { accountNav, toolsNav } from "@/app/layout/navigation";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton, SkeletonText } from "@/components/ui/States";
import type { MoveProfile, User } from "@/domain/profile";
import { useDocuments, useProfile, useSession, useUserGraph } from "@/lib/api/hooks";
import { formatDate, initials } from "@/lib/format";
import { InstallControl, useShowInstall } from "@/features/settings/InstallApp";
import { COMMUNITY_STATUS, FAITH_STATUS } from "@/features/settings/preferences";
import { LanguageSelector } from "@/i18n/LanguageSelector";
import { describeFactSources, moveRows, plural, summariseTwin } from "./summary";

function SectionTitle({ icon, children, id, action }: { icon: ReactNode; children: ReactNode; id: string; action?: ReactNode }) {
  useLocale();
  return (
    <div className="mb-3 flex items-center gap-2">
      <span className="text-subtle" aria-hidden>
        {localize(icon)}
      </span>
      <h2 id={id} className="flex-1 text-base font-medium">
        {localize(children)}
      </h2>
      {localize(action)}
    </div>
  );
}

// --- who they are -------------------------------------------------------------------------------

function Identity({ user }: { user: User | undefined }) {
  useLocale();
  const name = user?.displayName?.trim() || null;
  return (
    <header className="flex items-center gap-4">
      <span className="flex size-14 shrink-0 items-center justify-center rounded-full bg-ink font-display text-lg font-semibold text-canvas sm:size-16" aria-hidden>
        {initials(name) || <CircleUserRound className="size-7" />}
      </span>
      <div className="min-w-0">
        <h1 className="truncate text-3xl sm:text-4xl">{localize(name ?? tr("copy.your_profile_c1c9cbe"))}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
          <span className="inline-flex items-center gap-1.5">
            <LockKeyhole className="size-3.5 text-primary" aria-hidden />
            {tr("copy.private_to_you_c1b4514")}</span>
          {user?.createdAt && <span>{tr("copy.with_adapt_since_198a358")}{localize(formatDate(user.createdAt))}</span>}
          {user?.isDemo && <Badge tone="outline">{tr("copy.demo_workspace_8ac2bdb")}</Badge>}
        </div>
      </div>
    </header>
  );
}

// --- their move ------------------------------------------------------------------------------

function MoveDetails({ profile }: { profile: MoveProfile }) {
  useLocale();
  const rows = moveRows(profile);
  return (
    <Card tone="raised" className="overflow-hidden">
      <dl className="divide-y divide-line">
        {rows.map((row) => (
          <div key={row.key} className="grid grid-cols-[7rem_minmax(0,1fr)] gap-3 px-4 py-3.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4 sm:px-5">
            <dt className="text-sm text-muted">{localize(row.label)}</dt>
            <dd className="min-w-0">
              <span className="block text-sm font-medium">{localize(row.value)}</span>
              {row.detail && <span className="mt-0.5 block text-xs text-muted">{localize(row.detail)}</span>}
            </dd>
          </div>
        ))}
      </dl>
      {profile.note.trim() && (
        <figure className="border-t border-line px-5 py-4">
          <figcaption className="text-sm text-muted">{tr("copy.in_your_own_words_2a4827e")}</figcaption>
          <blockquote className="mt-1.5 border-s-2 border-primary/40 ps-3 text-sm whitespace-pre-line">{profile.note.trim()}</blockquote>
        </figure>
      )}
      <div className="flex flex-col gap-3 border-t border-line bg-muted-surface px-5 py-4 sm:flex-row sm:items-center">
        <div className="[&>a]:h-11 sm:[&>a]:h-10">
          <Link to="/onboarding" className={buttonClass("primary", "md", "w-full sm:w-auto")}>
            {tr("copy.update_my_move_79683ef")}</Link>
        </div>
        <p className="text-xs text-muted">{tr("copy.you_ll_review_your_answers_before_adapt_builds_a_e1f907b")}</p>
      </div>
    </Card>
  );
}

function YourMove() {
  useLocale();
  const profile = useProfile();
  return (
    <section aria-labelledby="profile-move">
      <SectionTitle id="profile-move" icon={<PlaneLanding className="size-4" />}>
        {tr("copy.your_move_44470e5")}</SectionTitle>
      {profile.isPending && (
        <Card tone="raised" className="p-5" role="status" aria-label={tr("copy.loading_your_move_9038659")}>
          <div className="flex flex-col gap-5">
            {localize(Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="grid grid-cols-[7rem_minmax(0,1fr)] gap-3 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="h-3.5 w-2/3" />
              </div>
            )))}
          </div>
        </Card>
      )}
      {profile.isError && <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />}
      {profile.isSuccess && profile.data === null && (
        <EmptyState
          icon={<PlaneLanding className="size-5" aria-hidden />}
          title={tr("copy.you_haven_t_told_adapt_about_your_move_yet_d7837d5")}
          description={tr("copy.answer_a_few_short_questions_about_your_move_hou_7c7e814")}
          action={
            <Link to="/onboarding" className={buttonClass("primary", "lg")}>
              {tr("copy.plan_my_move_7da4bc0")}</Link>
          }
        />
      )}
      {profile.data && <MoveDetails profile={profile.data} />}
    </section>
  );
}

// --- what ADAPT holds --------------------------------------------------------------------------

function HoldingRow({ to, icon: Icon, title, children }: { to: string; icon: LucideIcon; title: string; children: ReactNode }) {
  useLocale();
  return (
    <li>
      <Link to={to} className="group flex items-start gap-3 px-4 py-4 transition-colors hover:bg-muted-surface sm:px-5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sunken text-ink">
          <Icon className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium group-hover:underline group-hover:underline-offset-4">{localize(title)}</div>
          <div className="mt-0.5 text-sm text-muted">{localize(children)}</div>
        </div>
        <ChevronRight className="flip-rtl mt-2 size-4 shrink-0 text-subtle" aria-hidden />
      </Link>
    </li>
  );
}

function DocumentsSummary() {
  useLocale();
  const documents = useDocuments();
  if (documents.isPending) return <Skeleton className="mt-1 h-3.5 w-40" />;
  if (documents.isError) return <>{tr("copy.couldn_t_count_your_documents_open_documents_to__5be551e")}</>;
  const count = documents.data.length;
  const review = documents.data.filter((d) => d.status === "needs_review").length;
  return (
    <>
      {count === 0 ? tr("copy.no_documents_yet_1837bb9") : plural(count, "document", "documents")}
      {review > 0 && tr("copy.v0_waiting_for_your_review_4ade83e", { v0: review })}{tr("copy.encrypted_and_never_stored_on_this_device_b6a7d3f")}</>
  );
}

function TwinSummary() {
  useLocale();
  const graph = useUserGraph();
  if (graph.isPending) return <Skeleton className="mt-1 h-3.5 w-48" />;
  if (graph.isError) return <>{tr("copy.couldn_t_load_your_digital_twin_open_it_to_try_a_12c2bd3")}</>;
  const summary = summariseTwin(graph.data);
  if (summary.facts === 0) return <>{tr("copy.empty_until_you_tell_adapt_about_your_move_c771f7a")}</>;
  const sources = describeFactSources(summary);
  return (
    <>
      {localize(plural(summary.facts, "fact", "facts"))} {tr("copy.about_you_and_your_plans_6d99536")}{sources ? `: ${sources}` : ""}{tr("copy.text_3a52ce7")}</>
  );
}

function WhatAdaptHolds({ user }: { user: User | undefined }) {
  useLocale();
  const prefs = user?.preferences;
  return (
    <section aria-labelledby="profile-privacy">
      <SectionTitle id="profile-privacy" icon={<ShieldCheck className="size-4" />}>
        {tr("copy.what_adapt_holds_about_you_cd4efff")}</SectionTitle>
      <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
        <HoldingRow to="/documents" icon={FileText} title={tr("copy.documents_687c828")}>
          <DocumentsSummary />
        </HoldingRow>
        <HoldingRow to="/knowledge/me" icon={Network} title={tr("copy.my_digital_twin_a9d459f")}>
          <TwinSummary />
        </HoldingRow>
        <HoldingRow to="/settings" icon={SlidersHorizontal} title={tr("copy.personalisation_8ef1c70")}>
          {prefs ? (
            <>
              {tr("copy.community_suggestions_cf1aec5")}{localize(COMMUNITY_STATUS[prefs.communityPersonalization])}{tr("copy.places_of_worship_4e25bef")}{localize(FAITH_STATUS[prefs.faithPersonalization])}{tr("copy.voice_transcripts_5417cf6")}{prefs.voiceTranscriptsRetained ? tr("copy.kept_1e61fe1") : tr("copy.not_kept_0dfea39")}{tr("copy.text_3a52ce7")}</>
          ) : (
            <SkeletonText lines={2} className="mt-1" />
          )}
        </HoldingRow>
      </ul>
      <p className="mt-3 text-xs text-muted">{tr("copy.adapt_never_infers_your_faith_from_your_national_e04c272")}</p>
    </section>
  );
}

// --- tools and install ---------------------------------------------------------------------------

function YourTools() {
  useLocale();
  const items = [...toolsNav, ...accountNav.filter((item) => item.to === "/settings")];
  return (
    <section aria-labelledby="profile-tools">
      <SectionTitle id="profile-tools" icon={<Wrench className="size-4" />}>
        {tr("copy.your_tools_04309f8")}</SectionTitle>
      <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.to}>
              <Link to={item.to} className="group flex min-h-14 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted-surface">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-tint text-primary-strong">
                  <Icon className="size-[18px]" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium group-hover:underline group-hover:underline-offset-4">{localize(item.label)}</span>
                  <span className="block truncate text-xs text-muted">{localize(item.hint)}</span>
                </span>
                <ChevronRight className="flip-rtl size-4 shrink-0 text-subtle" aria-hidden />
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function InstallCard() {
  useLocale();
  const show = useShowInstall();
  if (!show) return null;
  return (
    <section aria-labelledby="profile-install">
      <SectionTitle id="profile-install" icon={<Smartphone className="size-4" />}>
        {tr("copy.install_adapt_250d11f")}</SectionTitle>
      <Card tone="flat" className="p-4">
        <p className="text-sm text-muted">{tr("copy.open_adapt_from_your_home_screen_or_dock_full_sc_a3adca7")}</p>
        <InstallControl className="mt-3" />
      </Card>
    </section>
  );
}

export default function ProfilePage() {
  useLocale();
  const session = useSession();

  if (session.isError) return <ErrorState error={session.error} onRetry={() => void session.refetch()} />;

  return (
    <div className="flex flex-col gap-8">
      <Identity user={session.data} />
      <section aria-label={tr("language.interface")} className="rounded-xl border border-line bg-surface p-4 lg:hidden">
        <p className="mb-3 text-sm font-medium">{tr("language.interface")}</p>
        <LanguageSelector className="w-full" />
      </section>
      <div className="grid gap-8 @4xl/main:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-8">
          <YourMove />
          <WhatAdaptHolds user={session.data} />
        </div>
        <aside className="flex min-w-0 flex-col gap-8" aria-label={tr("copy.tools_and_app_68bdb6e")}>
          <YourTools />
          <InstallCard />
        </aside>
      </div>
    </div>
  );
}
