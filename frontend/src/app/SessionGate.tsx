import { tr, localize, useLocale } from "@/i18n";
import { useQuery } from "@tanstack/react-query";
import { LockKeyhole, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ErrorState } from "@/components/ui/States";
import { Button } from "@/components/ui/Button";
import { useOnlineStatus } from "@/lib/hooks/useOnlineStatus";
import { useSession } from "@/lib/api/hooks";
import { config } from "@/lib/config";
import { ServicesProvider, useServerChanges, useServices } from "@/services/context";
import { liveSession } from "@/services/live/foundation";
import { createServices, type MockModule } from "@/services/registry";
import { requestedSeed } from "./demoSeed";
import { BrandMark } from "./layout/BrandMark";
import { LocaleSync } from "@/i18n/LocaleSync";
import { LanguagePicker } from "@/i18n/LanguageSelector";

function Splash({ label }: { label: string }) {
  useLocale();
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-5" role="status">
      <BrandMark className="size-12 animate-pulse" />
      <p className="text-sm text-muted">{localize(label)}</p>
    </div>
  );
}

function Failure({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  useLocale();
  return (
    <div className="flex min-h-dvh items-center justify-center p-6">
      <div className="w-full max-w-md">
        <BrandMark className="mb-6 size-10" />
        <ErrorState error={error} onRetry={onRetry} />
        {config.showDevBadge && config.dataMode !== "mock" && (
          <p className="mt-4 text-sm text-muted">
            {tr("copy.developers_start_the_backend_or_run_the_frontend_d087849")}<code className="rounded bg-sunken px-1">{tr("copy.vite_data_mode_mock_dc93ff2")}</code>{tr("copy.text_3a52ce7")}</p>
        )}
      </div>
    </div>
  );
}

function OfflineWorkspace() {
  useLocale();
  return <div className="flex min-h-dvh flex-col bg-canvas"><header className="flex h-16 items-center gap-3 border-b border-line bg-surface px-6"><BrandMark className="size-8" /><span className="font-display font-semibold">{tr("copy.adapt_2e26648")}</span><LanguagePicker className="ms-auto" /><span className="flex items-center gap-1.5 text-xs text-muted"><WifiOff className="size-3.5" aria-hidden />{tr("copy.offline_mode_66cf318")}</span></header><main className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center px-6 py-12"><span className="mb-5 flex size-14 items-center justify-center rounded-2xl bg-primary-tint text-primary"><WifiOff className="size-6" aria-hidden /></span><h1 className="text-3xl">{tr("copy.your_workspace_is_safe_98b05ab")}</h1><p className="mt-3 text-muted">{tr("copy.you_re_offline_reconnect_to_view_your_plan_check_e36463c")}</p><div className="private-banner mt-6 flex items-start gap-3 rounded-xl p-4"><LockKeyhole className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden /><p className="text-sm text-muted">{tr("copy.your_private_documents_and_personal_details_aren_837fb13")}</p></div><Button className="mt-6 self-start" onClick={() => window.location.reload()}>{tr("copy.try_again_042c862")}</Button><p className="mt-3 text-xs text-subtle" role="status">{tr("copy.adapt_will_reconnect_automatically_when_your_con_5d64d9e")}</p></main></div>;
}

/**
 * Developer and demo shortcut: `?seed=sample` loads the sample plan when journeys come from
 * mocks (never against a real journey API).
 */
function useSampleSeed(): boolean {
  const services = useServices();
  const [pending, setPending] = useState(() => requestedSeed === "sample" && services.demo !== null);
  useEffect(() => {
    if (!pending || !services.demo) return;
    void services.demo.seedSample().finally(() => setPending(false));
  }, [pending, services]);
  return pending;
}

/** Establishes the private session. In demo deployments a private account is created on first visit. */
function SessionGate({ children }: { children: ReactNode }) {
  useLocale();
  const session = useSession();
  const seeding = useSampleSeed();
  // Follow server-side changes only once there is a session to read them with.
  useServerChanges(session.isSuccess);
  if (session.isPending || seeding) return <Splash label={tr("copy.preparing_your_private_workspace_3289bb4")} />;
  if (session.isError) return <Failure error={session.error} onRetry={() => void session.refetch()} />;
  return <><LocaleSync />{children}</>;
}

/**
 * Resolves where each capability's data comes from (live API or typed mocks, from
 * `/system/info` feature flags and `VITE_DATA_MODE`), then opens the session.
 */
export function Bootstrap({ children }: { children: ReactNode }) {
  const uiLocale = useLocale();
  const online = useOnlineStatus();
  const info = useQuery({
    queryKey: ["bootstrap", config.dataMode],
    queryFn: async ({ signal }) => {
      // The mock layer is its own chunk, never loaded in `live` mode.
      const mock: MockModule | null = config.dataMode === "live" ? null : await import("@/services/mock");
      const system = config.dataMode === "mock" && mock ? await mock.mockSession.systemInfo(signal) : await liveSession.systemInfo(signal);
      return { system, mock };
    },
    staleTime: Infinity,
    structuralSharing: false,
    retry: 2,
    enabled: online,
  });
  const services = useMemo(() => (info.data ? createServices(config.dataMode, info.data.system, info.data.mock) : null), [info.data, uiLocale]);

  if (!online && !info.data) return <OfflineWorkspace />;
  if (info.isPending) return <Splash label={tr("copy.starting_adapt_d7ae61b")} />;
  if (info.isError || !services) return <Failure error={info.error} onRetry={() => void info.refetch()} />;
  return (
    <ServicesProvider services={services}>
      <SessionGate>{localize(children)}</SessionGate>
    </ServicesProvider>
  );
}

export { Splash };
