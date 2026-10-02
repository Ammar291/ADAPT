import { tr, localize, useLocale } from "@/i18n";
import { WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { useRegisterSW } from "virtual:pwa-register/react";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useDiscoverActions, useResearchStatus, useSystemInfo } from "@/lib/api/hooks";
import { config } from "@/lib/config";
import { useOnlineStatus } from "@/lib/hooks/useOnlineStatus";
import { useServices } from "@/services/context";

export function OfflineBanner() {
  useLocale();
  const online = useOnlineStatus();
  if (online) return null;
  return (
    <div role="status" className="flex items-center gap-2 bg-ink px-4 py-2 text-sm text-canvas">
      <WifiOff className="size-4 shrink-0" aria-hidden />
      {tr("copy.you_re_offline_reconnect_to_save_changes_and_che_fe564f2")}</div>
  );
}

/** Asks before activating a new service worker, so an update never interrupts a task. */
export function UpdatePrompt() {
  useLocale();
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({ immediate: true });
  if (!needRefresh || config.demoMode) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-[calc(4rem+env(safe-area-inset-bottom)+5rem)] z-50 mx-auto flex max-w-md items-center gap-3 rounded-lg border border-line bg-surface p-3 shadow-overlay lg:bottom-6"
    >
      <p className="flex-1 text-sm">{tr("copy.a_new_version_of_adapt_is_ready_36464f8")}</p>
      <Button size="sm" variant="ghost" onClick={() => setNeedRefresh(false)}>
        {tr("copy.later_56e2f5d")}</Button>
      <Button size="sm" onClick={() => void updateServiceWorker(true)}>
        {tr("copy.reload_cce7155")}</Button>
    </div>
  );
}

/**
 * Announces "Your Abu Dhabi Life Brief is ready." once, when background research finishes
 * (or on load if it finished while the user was away and they haven't seen it).
 */
export function LifeBriefNotifier() {
  useLocale();
  const status = useResearchStatus();
  const { markSeen } = useDiscoverActions();
  const announced = useRef<string | null>(null);
  const { pathname } = useLocation();
  // Discover and the demo page show the research themselves.
  const onDiscover = pathname.startsWith("/discover") || pathname.startsWith("/demo");

  useEffect(() => {
    const s = status.data;
    // Discover marks the brief as seen itself; no need to point there from there.
    if (onDiscover || !s?.briefReady || s.seen || !s.jobId || announced.current === s.jobId) return;
    announced.current = s.jobId;
    const jobId = s.jobId;
    toast({
      title: tr("copy.your_abu_dhabi_life_brief_is_ready_b028cbc"),
      description: tr("copy.v0_places_communities_and_tips_picked_for_you_53d0e72", { v0: s.itemCount }),
      tone: "info",
      duration: 6000,
      action: { label: tr("copy.open_discover_5525c87"), to: "/discover" },
      onDismiss: () => markSeen.mutate(jobId),
    });
  }, [status.data, markSeen, onDiscover]);

  return null;
}

/**
 * Developer-only indicator of what's simulated: backend demo adapters and frontend mocks.
 * Controlled by VITE_SHOW_DEV_BADGE (on in development, off in production builds).
 */
export function DevBadge() {
  useLocale();
  const info = useSystemInfo();
  const { sources } = useServices();
  const [expanded, setExpanded] = useState(false);
  if (!config.showDevBadge) return null;
  const mocked = Object.entries(sources).filter(([, s]) => s !== "live");
  const demoAdapters = info.data?.adapters.filter((a) => a.mode === "demo") ?? [];

  return (
    <div className="fixed start-3 bottom-[calc(4rem+env(safe-area-inset-bottom)+0.75rem)] z-50 lg:start-auto lg:end-3 lg:top-3 lg:bottom-auto">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className="rounded-md border border-dashed border-dune bg-dune-tint px-2 py-1 font-mono text-[11px] text-dune"
      >
        {tr("copy.dev_7a4fd27")}{localize(config.dataMode)} {tr("copy.text_ddb36e6")}{localize(mocked.length)} {tr("copy.mocked_899ab17")}</button>
      {expanded && (
        <div className="mt-2 w-80 rounded-md border border-line bg-surface p-3 text-xs shadow-overlay">
          <p className="mb-2 font-medium">{tr("copy.data_sources_be6ef20")}{localize(config.dataMode)} {tr("copy.mode_3f9df18")}</p>
          <ul className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(sources).map(([capability, source]) => (
              <li key={capability} className="flex justify-between gap-2">
                <span className="text-muted">{localize(capability)}</span>
                <span className={source === "live" ? "text-primary" : source === "mock" ? "text-dune" : "text-danger"}>{localize(source)}</span>
              </li>
            ))}
          </ul>
          {info.data && (
            <>
              <p className="mb-1 font-medium">
                {tr("copy.backend_7338324")}{localize(info.data.environment)}{tr("copy.v_37a963c")}{localize(info.data.version)}
              </p>
              <p className="text-muted">
                {demoAdapters.length ? tr("copy.demo_adapters_v0_31ebf6c", { v0: demoAdapters.map((a) => a.capability).join(", ") }) : tr("copy.all_adapters_live_a77fde9")}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
