import { tr } from "@/i18n";
import {
  AudioLines,
  CircleUserRound,
  Compass,
  FileText,
  Hand,
  House,
  Landmark,
  Languages,
  LockKeyhole,
  Route,
  Settings,
  Split,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Short description, used where items are listed with context (Profile's tool list). */
  hint: string;
}

/** Everyday destinations. */
export const mainNav: NavItem[] = [
  { to: "/home", label: tr("copy.home_70f8bb9", { lng: "en" }), icon: House, hint: tr("copy.what_to_do_next_8ce2518", { lng: "en" }) },
  { to: "/journey", label: tr("copy.journey_e40c092", { lng: "en" }), icon: Route, hint: tr("copy.every_step_in_order_612e31a", { lng: "en" }) },
  { to: "/approvals", label: tr("copy.approvals_deb9d03", { lng: "en" }), icon: Hand, hint: tr("copy.waiting_for_your_approval_5095847", { lng: "en" }) },
  { to: "/discover", label: tr("copy.discover_4827ea2", { lng: "en" }), icon: Compass, hint: tr("copy.communities_events_and_culture_4ed9c67", { lng: "en" }) },
  { to: "/documents", label: tr("copy.documents_687c828", { lng: "en" }), icon: FileText, hint: tr("copy.your_documents_and_drafts_a021eab", { lng: "en" }) },
];

/** Understanding and planning tools. */
export const toolsNav: NavItem[] = [
  { to: "/knowledge/governance", label: tr("copy.governance_823619e", { lng: "en" }), icon: Landmark, hint: tr("copy.official_rules_services_and_sources_14bdcbe", { lng: "en" }) },
  { to: "/knowledge/me", label: tr("copy.digital_twin_459f903", { lng: "en" }), icon: LockKeyhole, hint: tr("copy.your_private_facts_and_connections_7ef7742", { lng: "en" }) },
  { to: "/agents", label: tr("copy.agents_64acf7e", { lng: "en" }), icon: Workflow, hint: tr("copy.watch_adapt_work_step_by_step_5e7648c", { lng: "en" }) },
  { to: "/simulate", label: tr("copy.what_if_fd0b7c0", { lng: "en" }), icon: Split, hint: tr("copy.try_a_different_decision_b0da957", { lng: "en" }) },
  { to: "/assistant", label: tr("copy.assistant_8010d1f", { lng: "en" }), icon: AudioLines, hint: tr("copy.talk_or_type_to_adapt_e4fe410", { lng: "en" }) },
  { to: "/interpreter", label: tr("interpreter.title", { lng: "en" }), icon: Languages, hint: tr("interpreter.description", { lng: "en" }) },
];

export const accountNav: NavItem[] = [
  { to: "/profile", label: tr("copy.profile_ff4fc02", { lng: "en" }), icon: CircleUserRound, hint: tr("copy.your_move_and_your_data_af1d1e6", { lng: "en" }) },
  { to: "/settings", label: tr("copy.settings_c7f73bb", { lng: "en" }), icon: Settings, hint: tr("copy.language_privacy_appearance_1365886", { lng: "en" }) },
];

/** The mobile bottom bar shows exactly these five; Approvals is reached from Home and the menu. */
export const bottomNav: NavItem[] = [...mainNav.filter((item) => item.to !== "/approvals"), accountNav[0]!];

export const allNav = [...mainNav, ...toolsNav, ...accountNav];

export function titleFor(pathname: string): string {
  const match = allNav
    .filter((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return match?.label ?? (pathname.startsWith("/demo") ? tr("copy.founder_arrival_257c193") : tr("copy.adapt_2e26648"));
}
