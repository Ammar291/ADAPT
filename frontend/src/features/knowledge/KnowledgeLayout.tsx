import { tr, localize, useLocale } from "@/i18n";
import { Landmark, Lock } from "lucide-react";
import { useRef, type KeyboardEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { cn } from "@/lib/cn";

const TABS = [
  { to: "/knowledge/governance", label: tr("copy.official_rules_685278f", { lng: "en" }), hint: tr("copy.public_knowledge_1881f24", { lng: "en" }), icon: Landmark },
  { to: "/knowledge/me", label: tr("copy.my_digital_twin_a9d459f", { lng: "en" }), hint: tr("copy.only_you_can_see_this_5bd0cb8", { lng: "en" }), icon: Lock },
] as const;

/** Knowledge: the public governance graph and the private twin, as two tabs (route links). */
export default function KnowledgeLayout() {
  useLocale();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const refs = useRef<(HTMLAnchorElement | null)[]>([]);
  const active = Math.max(
    0,
    TABS.findIndex((tab) => pathname === tab.to || pathname.startsWith(`${tab.to}/`)),
  );

  // Arrow keys move between tabs (roving tabindex), mirrored in right-to-left layouts.
  const onKeyDown = (event: KeyboardEvent<HTMLAnchorElement>, index: number) => {
    const rtl = getComputedStyle(event.currentTarget).direction === "rtl";
    const n = TABS.length;
    const next =
      event.key === (rtl ? "ArrowLeft" : "ArrowRight")
        ? (index + 1) % n
        : event.key === (rtl ? "ArrowRight" : "ArrowLeft")
          ? (index - 1 + n) % n
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? n - 1
              : null;
    if (next === null) return;
    event.preventDefault();
    refs.current[next]?.focus();
    navigate(TABS[next]!.to);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 px-4 pt-5 sm:px-6 lg:px-8 lg:pt-6">
        <h1 className="text-2xl">{active === 0 ? tr("copy.abu_dhabi_connected_af56778") : tr("copy.your_digital_twin_111e8b1")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          {active === 0 ? tr("copy.explore_the_services_requirements_and_authoritie_a593435") : tr("copy.your_people_documents_and_plans_connected_to_the_f07631f")}
        </p>
      </header>
      <div role="tablist" aria-label={tr("copy.knowledge_graphs_d9256a9")} className="mt-3 flex shrink-0 gap-1 border-b border-line px-4 sm:gap-2 sm:px-6 lg:px-8">
        {TABS.map((tab, i) => {
          const selected = i === active;
          const Icon = tab.icon;
          return (
            <NavLink
              key={tab.to}
              ref={(el) => {
                refs.current[i] = el;
              }}
              to={tab.to}
              id={`knowledge-tab-${i}`}
              role="tab"
              aria-selected={selected}
              aria-controls="knowledge-panel"
              tabIndex={selected ? 0 : -1}
              onKeyDown={(event) => onKeyDown(event, i)}
              className={cn(
                "relative -mb-px flex min-h-12 min-w-0 flex-1 flex-col justify-center border-b-2 px-2 py-2 transition-colors sm:flex-none sm:px-3",
                selected ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink",
              )}
            >
              <span className="text-sm font-medium leading-tight">{localize(tab.label)}</span>
              <span className={cn("mt-0.5 flex items-center gap-1 text-2xs leading-tight", i === 1 ? "text-primary-strong" : "text-subtle")}>
                <Icon className="size-3 shrink-0" aria-hidden />
                {localize(tab.hint)}
              </span>
            </NavLink>
          );
        })}
      </div>
      <div role="tabpanel" id="knowledge-panel" aria-labelledby={`knowledge-tab-${active}`} className="flex min-h-0 flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  );
}
