import { tr } from "@/i18n";
import { useEffect, useState } from "react";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferred = event as BeforeInstallPromptEvent;
    listeners.forEach((l) => l());
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    listeners.forEach((l) => l());
  });
}

function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia(tr("copy.display_mode_standalone_a11dbc0")).matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

/**
 * Installing ADAPT as an app.
 *   canPrompt   — the browser offered an install prompt (Chrome, Edge, Android)
 *   iosHint     — Safari on iOS: install via Share, then "Add to Home Screen"
 *   installed   — already running as an installed app
 */
export function usePwaInstall() {
  const [, force] = useState(0);
  useEffect(() => {
    const update = () => force((n) => n + 1);
    listeners.add(update);
    return () => {
      listeners.delete(update);
    };
  }, []);

  const installed = isStandalone();
  return {
    installed,
    canPrompt: !installed && deferred !== null,
    iosHint: !installed && deferred === null && isIos(),
    async install(): Promise<"accepted" | "dismissed" | "unavailable"> {
      if (!deferred) return "unavailable";
      const event = deferred;
      await event.prompt();
      const { outcome } = await event.userChoice;
      deferred = null;
      listeners.forEach((l) => l());
      return outcome;
    },
  };
}
