import { tr, useLocale } from "@/i18n";
import { Download, Share, SquarePlus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { usePwaInstall } from "@/lib/hooks/usePwaInstall";

/** Whether an install row should show at all: hidden once ADAPT runs as an installed app. */
export function useShowInstall(): boolean {
  return !usePwaInstall().installed;
}

/**
 * The install control for Profile and Settings:
 *   the browser offered a prompt → "Install ADAPT" button
 *   Safari on iOS               → Share, then Add to Home Screen
 *   otherwise                   → where to look in the browser menu
 *   already installed           → nothing
 */
export function InstallControl({ className }: { className?: string }) {
  useLocale();
  const pwa = usePwaInstall();
  const [busy, setBusy] = useState(false);
  if (pwa.installed) return null;

  if (pwa.canPrompt) {
    return (
      <Button
        variant="secondary"
        className={className}
        loading={busy}
        icon={<Download className="size-4" aria-hidden />}
        onClick={async () => {
          setBusy(true);
          try {
            const outcome = await pwa.install();
            if (outcome === "accepted") toast({ title: tr("copy.adapt_is_being_installed_15b5718"), description: tr("copy.open_it_from_your_home_screen_or_app_list__49efab2") });
            if (outcome === "unavailable") toast({ title: tr("copy.your_browser_didn_t_offer_an_install_4881d1e"), description: tr("copy.use_install_or_add_to_home_screen_in_the_browser_38d862c"), tone: "info" });
          } finally {
            setBusy(false);
          }
        }}
      >
        {tr("copy.install_adapt_250d11f")}</Button>
    );
  }

  if (pwa.iosHint) {
    return (
      <ol className={cn("flex flex-col gap-2 text-sm", className)}>
        <li className="flex items-center gap-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sunken text-ink">
            <Share className="size-4" aria-hidden />
          </span>
          {tr("copy.in_safari_tap_share_55f1d0c")}</li>
        <li className="flex items-center gap-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sunken text-ink">
            <SquarePlus className="size-4" aria-hidden />
          </span>
          {tr("copy.choose_add_to_home_screen_1137007")}</li>
      </ol>
    );
  }

  return (
    <p className={cn("text-sm text-muted", className)}>
      {tr("copy.if_your_browser_supports_it_choose_install_adapt_8cc4de5")}</p>
  );
}
