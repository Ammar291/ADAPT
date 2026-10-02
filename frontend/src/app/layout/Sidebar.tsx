import { tr, localize, useLocale } from "@/i18n";
import { ArrowUpRight, LockKeyhole, Search } from "lucide-react";
import { Link, NavLink } from "react-router";
import { useApprovals, useSession } from "@/lib/api/hooks";
import { useUiStore } from "@/stores/ui";
import { cn } from "@/lib/cn";
import { initials } from "@/lib/format";
import { Wordmark } from "./BrandMark";
import { accountNav, mainNav, toolsNav, type NavItem } from "./navigation";

function SidebarLink({ item, badge }: { item: NavItem; badge?: number }) {
  useLocale();
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      className={({ isActive }) =>
        cn(
          "sidebar-link group flex h-11 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
          isActive ? "sidebar-link-active font-medium" : "",
        )
      }
    >
      {localize(() => (
        <>
          <Icon className="size-[18px] shrink-0" aria-hidden />
          <span className="flex-1">{localize(item.label)}</span>
          {badge ? (
            <span className="tabular rounded-full bg-[#b4dcd7] px-1.5 text-2xs font-semibold text-[#0f292d]" aria-label={localize(tr("copy.v0_waiting_for_you_d6094ed", { v0: badge }))}>
              {localize(badge)}
            </span>
          ) : null}
        </>
      ))}
    </NavLink>
  );
}

export function Sidebar() {
  useLocale();
  const session = useSession();
  const approvals = useApprovals("pending");
  const name = session.data?.displayName?.trim() || tr("copy.your_account_4ab2910");
  const pending = approvals.data?.length ?? 0;
  const openSearch = useUiStore((s) => s.setSearchOpen);

  return (
    <aside className="workspace-sidebar sticky top-0 hidden h-dvh w-[232px] shrink-0 flex-col lg:flex">
      <div className="px-6 pt-6 pb-5">
        <Wordmark inverse />
        <p className="mt-2 text-xs text-[#91a6ae]">{tr("copy.a_new_chapter_in_abu_dhabi_fc73f50")}</p>
      </div>
      <button type="button" onClick={() => openSearch(true)} className="mx-4 mb-6 flex h-10 items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-3 text-sm text-[#afc0c7] hover:bg-white/10"><Search className="size-4" aria-hidden /><span className="flex-1 text-start">{tr("copy.search_bce0641")}</span><kbd className="text-2xs opacity-70">{tr("copy.ctrl_k_a784e36")}</kbd></button>
      <nav aria-label={tr("copy.main_62bce94")} className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-3">
        <div className="flex flex-col gap-0.5">
          <p className="px-3 pb-2 text-[10px] font-medium uppercase tracking-[0.14em] text-[#91a6ae]">{tr("copy.your_move_44470e5")}</p>
          {mainNav.map((item) => (
            <SidebarLink key={item.to} item={item} badge={item.to === "/documents" ? pending : undefined} />
          ))}
        </div>
        <div className="flex flex-col gap-0.5">
          <p className="px-3 pb-2 text-[10px] font-medium uppercase tracking-[0.14em] text-[#91a6ae]">{tr("copy.explore_plan_d13f1ab")}</p>
          {toolsNav.map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}
        </div>
        <div className="mt-auto flex flex-col gap-0.5 pb-3">
          {accountNav.slice(1).map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}
        </div>
      </nav>
      <Link to="/assistant" className="mx-4 mb-4 rounded-xl border border-white/10 bg-white/5 p-3.5 hover:bg-white/10"><span className="flex items-center justify-between text-xs font-medium text-[#dcece9]">{tr("copy.a_little_guidance_anytime_6fead81")}<ArrowUpRight className="size-3.5" aria-hidden /></span><span className="mt-1.5 block text-xs leading-relaxed text-[#91a6ae]">{tr("copy.ask_adapt_about_your_next_step_fce18e5")}</span></Link>
      <NavLink
        to="/profile"
        className={({ isActive }) =>
          cn("flex items-center gap-3 border-t border-white/10 px-5 py-4 transition-colors hover:bg-white/5", isActive && "bg-white/5")
        }
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#345356] text-2xs font-semibold text-[#dcece9]" aria-hidden>
          {localize(initials(session.data?.displayName) || "·")}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-[#e9f0f2]">{localize(name)}</span>
          <span className="mt-1 flex items-center gap-1 text-2xs text-[#91a6ae]"><LockKeyhole className="size-3" aria-hidden />{tr("copy.private_to_you_c1b4514")}</span>
        </span>
      </NavLink>
    </aside>
  );
}
