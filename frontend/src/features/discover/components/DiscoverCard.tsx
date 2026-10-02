import { tr, localize, useLocale } from "@/i18n";
import { BadgeCheck, Bookmark, BookmarkCheck, Building2, CalendarDays, ExternalLink, Globe, Mail, MapPin, Phone, Plus, Route, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Button, buttonClass } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Controls";
import { toast } from "@/components/ui/Toast";
import { TrustBadge } from "@/components/ui/TrustBadge";
import { domainOf, safeWebUrl } from "@/domain/common";
import { SOURCE_LABEL_TEXT, type DiscoverContact, type DiscoverItem, type DiscoverSource, type SourceLabel } from "@/domain/discover";
import { describeError, isApiError } from "@/lib/api/errors";
import { useDiscoverActions } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { isStale } from "../lib/discover";

/** The source's weight, as words with an icon: the only quality signal shown. */
const SOURCE_STYLE: Record<SourceLabel, { icon: typeof Globe; className: string }> = {
  official: { icon: BadgeCheck, className: "text-civic" },
  organization: { icon: Building2, className: "text-muted" },
  community: { icon: Users, className: "text-dune" },
  general_web: { icon: Globe, className: "text-muted" },
};

export function SourceLabelText({ label, className }: { label: SourceLabel; className?: string }) {
  useLocale();
  const style = SOURCE_STYLE[label];
  const Icon = style.icon;
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 font-medium", style.className, className)}>
      <Icon className="size-3.5" aria-hidden />
      {localize(SOURCE_LABEL_TEXT[label])}
      <span className="sr-only"> {tr("copy.source_828d338")}</span>
    </span>
  );
}

function SourceName({ source }: { source: DiscoverSource }) {
  useLocale();
  const url = safeWebUrl(source.url);
  const domain = source.domain ?? (source.url ? domainOf(source.url) : null);
  const body = (
    <>
      <span className="text-ink">{localize(source.title)}</span>
      {domain && <span className="ms-1.5 text-subtle">{localize(domain)}</span>}
    </>
  );
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className="min-w-0 hover:underline hover:underline-offset-4">
      {localize(body)}
      <span className="sr-only"> {tr("copy.opens_in_a_new_tab_bf5b990")}</span>
    </a>
  ) : (
    <span className="min-w-0">{localize(body)}</span>
  );
}

const CONTACT_ICON: Record<DiscoverContact["kind"], typeof Globe> = { website: Globe, email: Mail, phone: Phone, address: MapPin };

function contactHref(contact: DiscoverContact): string | null {
  switch (contact.kind) {
    case "website":
      return safeWebUrl(contact.value);
    case "email":
      return `mailto:${contact.value}`;
    case "phone":
      return `tel:${contact.value.replace(/[^\d+]/g, "")}`;
    default:
      return null;
  }
}

function SampleLabel() {
  useLocale();
  return (
    <Tooltip content={tr("copy.example_content_check_the_source_before_relying__c7bea04")}>
      <span
        tabIndex={0}
        className="inline-flex h-6 shrink-0 cursor-help items-center rounded-full bg-sunken px-2.5 text-2xs font-medium text-muted"
        aria-label={tr("copy.sample_example_content_check_the_source_before_r_b583e11")}
      >
        {tr("copy.sample_58fabfa")}</span>
    </Tooltip>
  );
}

export type CardVariant = "feature" | "lead" | "standard" | "row";

/**
 * One research result: why it fits, what it is, where it comes from and when that was last
 * checked, with Open, Save and Add to journey. Community results read as suggestions, never
 * as requirements. `feature` lays the card out in two columns when there's room; `row` is the
 * same layout without a frame, for divided lists.
 */
export function DiscoverCard({ item, variant = "standard", className }: { item: DiscoverItem; variant?: CardVariant; className?: string }) {
  useLocale();
  const { save, addToJourney } = useDiscoverActions();
  const [needsPlan, setNeedsPlan] = useState(false);
  const saving = save.isPending && save.variables?.id === item.id;
  const adding = addToJourney.isPending && addToJourney.variables === item.id;
  const stale = isStale(item);
  const titleId = `discover-${item.id}`;
  const sourceUrl = safeWebUrl(item.source.url);
  const domain = item.source.domain ?? (item.source.url ? domainOf(item.source.url) : null);
  const large = variant === "feature" || variant === "lead";

  const add = () =>
    addToJourney.mutate(item.id, {
      onSuccess: (updated) => {
        setNeedsPlan(false);
        toast({
          title: tr("copy.added_to_your_journey_d8e08c1"),
          description: tr("copy.v0_is_now_an_optional_step_under_community_b4aa4c9", { v0: item.title }),
          action: updated.journeyNodeId ? { label: tr("copy.see_it_in_your_journey_89f42f5"), to: `/journey?node=${encodeURIComponent(updated.journeyNodeId)}` } : undefined,
        });
      },
      onError: (error) => {
        if (isApiError(error, "journey_required")) setNeedsPlan(true);
        else toast({ title: describeError(error).title, description: describeError(error).detail, tone: "error" });
      },
    });

  const toggleSave = () =>
    save.mutate(
      { id: item.id, saved: !item.saved },
      { onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail, tone: "error" }) },
    );

  const badges = (
    <div className="flex flex-wrap items-center gap-2">
      <TrustBadge kind={item.evidenceKind} cultural={item.section === "culture"} />
      {item.isSample && <SampleLabel />}
      {item.saved && (
        <span className="inline-flex items-center gap-1 text-2xs font-medium text-primary-strong">
          <BookmarkCheck className="size-3.5" aria-hidden />
          {tr("copy.saved_c0ae8f6")}</span>
      )}
    </div>
  );

  const body = (
    <>
      <h3 id={titleId} className={cn("mt-3 leading-snug", variant === "feature" ? "text-2xl" : large ? "text-xl" : "text-lg")}>
        {localize(item.title)}
      </h3>
      {item.relevance && (
        <div className="mt-3 border-s-2 border-primary/40 ps-3">
          <p className="text-2xs font-medium text-muted">{tr("copy.why_this_is_relevant_d4cc7d2")}</p>
          <p className={cn("mt-0.5", large ? "text-base" : "text-sm")}>{localize(item.relevance)}</p>
        </div>
      )}
      <p className={cn("mt-3 text-muted", large ? "text-base" : "text-sm")}>{localize(item.summary)}</p>
    </>
  );

  const facts =
    item.when || item.where || item.contacts.length > 0 ? (
      <div className="flex flex-col gap-3">
        {(item.when || item.where) && (
          <dl className="flex flex-col gap-1.5 text-sm">
            {item.when && (
              <div className="flex items-start gap-2">
                <dt>
                  <CalendarDays className="mt-0.5 size-4 text-subtle" aria-hidden />
                  <span className="sr-only">{tr("copy.when_769bb19")}</span>
                </dt>
                <dd>{localize(item.when)}</dd>
              </div>
            )}
            {item.where && (
              <div className="flex items-start gap-2">
                <dt>
                  <MapPin className="mt-0.5 size-4 text-subtle" aria-hidden />
                  <span className="sr-only">{tr("copy.where_525f61b")}</span>
                </dt>
                <dd>{localize(item.where)}</dd>
              </div>
            )}
          </dl>
        )}
        {item.contacts.length > 0 && (
          <ul className="flex flex-col gap-1.5 text-sm" aria-label={tr("copy.contact_details_d4ec65a")}>
            {item.contacts.map((contact) => {
              const Icon = CONTACT_ICON[contact.kind];
              const href = contactHref(contact);
              return (
                <li key={`${contact.kind}:${contact.value}`} className="flex min-w-0 items-start gap-2">
                  <Icon className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
                  <span className="min-w-0">
                    {href ? (
                      <a
                        href={href}
                        className="break-words text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink"
                        {...(contact.kind === "website" ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                      >
                        {localize(contact.value)}
                      </a>
                    ) : (
                      <span className="break-words">{localize(contact.value)}</span>
                    )}
                    <span className="ms-2 text-2xs text-subtle">{tr("copy.listed_on_4199a56")}{localize(domainOf(contact.sourceUrl))}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    ) : null;

  const source = (
    <div className="text-xs">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <SourceLabelText label={item.source.label} />
        <SourceName source={item.source} />
      </p>
      <p className="mt-1 flex flex-wrap gap-x-2 text-2xs text-subtle">
        {item.retrieval && <span>{item.retrieval.method === "live_web_search" ? tr("copy.live_web_search_263aa4f") : tr("copy.curated_source_snapshot_70743f8")}</span>}
        <span>{tr("copy.last_checked_7d5b4eb")}{localize(formatDate(item.lastCheckedAt))}</span>
        {stale && <span className="font-medium text-ink">{tr("copy.may_be_out_of_date_3e37b97")}</span>}
      </p>
      {item.moreSources.length > 0 && (
        <div className="mt-2">
          <p className="text-2xs text-muted">{tr("copy.also_on_f4c9f30")}</p>
          <ul className="mt-0.5 flex flex-col gap-0.5">
            {item.moreSources.map((more) => (
              <li key={more.url ?? more.title} className="flex flex-wrap items-center gap-x-2">
                <SourceLabelText label={more.label} className="text-2xs" />
                <SourceName source={more} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );

  const actions = (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {sourceUrl ? (
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className={buttonClass("secondary", "sm")}>
            {tr("copy.open_cf9b770")}<ExternalLink className="size-3.5" aria-hidden />
            <span className="sr-only">
              {localize(item.title)} {tr("copy.on_03fcaa9")}{localize(domain)} {tr("copy.opens_in_a_new_tab_bf5b990")}</span>
          </a>
        ) : (
          <Button size="sm" variant="secondary" disabled title={tr("copy.there_s_no_public_page_for_this_example_1fcf7ae")}>
            {tr("copy.open_cf9b770")}<ExternalLink className="size-3.5" aria-hidden />
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          aria-pressed={item.saved}
          loading={saving}
          onClick={toggleSave}
          icon={item.saved ? <BookmarkCheck className="size-4 text-primary" aria-hidden /> : <Bookmark className="size-4" aria-hidden />}
        >
          {item.saved ? tr("copy.saved_c0ae8f6") : tr("copy.save_efc007a")}
          <span className="sr-only"> {localize(item.title)}</span>
        </Button>
        {item.journeyNodeId ? (
          <Link to={`/journey?node=${encodeURIComponent(item.journeyNodeId)}`} className={buttonClass("ghost", "sm", "text-primary-strong")}>
            <Route className="size-4" aria-hidden />
            {tr("copy.in_your_journey_6ce64bb")}</Link>
        ) : (
          <Button size="sm" variant="ghost" loading={adding} onClick={add} icon={<Plus className="size-4" aria-hidden />}>
            {tr("copy.add_to_journey_37d021d")}</Button>
        )}
      </div>
      {needsPlan && (
        <p role="status" className="mt-2 text-sm text-muted">
          {tr("copy.build_your_plan_first_0c8be9f")}{localize(" ")}
          <Link to="/onboarding" className="font-medium text-primary-strong underline underline-offset-4">
            {tr("copy.plan_my_move_7da4bc0")}</Link>
        </p>
      )}
    </div>
  );

  if (variant === "feature" || variant === "row") {
    return (
      <article
        aria-labelledby={titleId}
        className={cn(
          "@container min-w-0",
          variant === "feature" ? "rounded-xl border border-line-strong/70 bg-surface p-5 shadow-raised sm:p-6" : "px-5 py-5",
          className,
        )}
      >
        <div className="grid gap-5 @2xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] @2xl:gap-10">
          <div className="min-w-0">
            {localize(badges)}
            {localize(body)}
          </div>
          <div className="flex min-w-0 flex-col gap-4 border-t border-line pt-4 @2xl:border-s @2xl:border-t-0 @2xl:ps-8 @2xl:pt-1">
            {localize(facts)}
            {localize(source)}
            <div className="@2xl:mt-auto">{localize(actions)}</div>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article
      aria-labelledby={titleId}
      className={cn(
        "flex h-full min-w-0 flex-col rounded-xl border bg-surface p-5",
        large ? "border-line-strong/70 shadow-raised sm:p-6" : "border-line",
        className,
      )}
    >
      {localize(badges)}
      {localize(body)}
      {facts && <div className="mt-3">{localize(facts)}</div>}
      <div className="mt-auto pt-4">
        <div className="border-t border-line pt-3">{localize(source)}</div>
        <div className="mt-4">{localize(actions)}</div>
      </div>
    </article>
  );
}
