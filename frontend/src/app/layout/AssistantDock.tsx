import { tr, useLocale } from "@/i18n";
import { AudioLines, Maximize2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef } from "react";
import { Link, useLocation } from "react-router";
import { IconButton } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { AssistantPanel } from "@/features/assistant/AssistantPanel";
import { selectIsLive } from "@/features/voice/selectors";
import { useVoiceStore } from "@/features/voice/store";
import { cn } from "@/lib/cn";
import { useIsDesktop } from "@/lib/hooks/useMediaQuery";
import { useUiStore } from "@/stores/ui";

/** Floating entry point to the assistant, reachable from every screen. */
export function AssistantFab() {
  useLocale();
  const open = useUiStore((s) => s.assistantOpen);
  const setOpen = useUiStore((s) => s.setAssistantOpen);
  const live = useVoiceStore(selectIsLive);
  const { pathname } = useLocation();
  if (pathname === "/assistant") return null;
  return (
    <AnimatePresence>
      {!open && (
        <motion.button
          type="button"
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.8, opacity: 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 28 }}
          onClick={() => setOpen(true)}
          aria-label={live ? tr("copy.return_to_your_conversation_with_adapt_36638a2") : tr("copy.talk_to_adapt_c9461e0")}
          className={cn(
            "fixed end-4 z-40 hidden h-14 items-center gap-2 rounded-full ps-4 pe-5 lg:flex",
            "bg-ink text-canvas shadow-overlay transition-colors hover:bg-ink/90 active:scale-95",
            "bottom-[calc(4rem+env(safe-area-inset-bottom)+1rem)] lg:end-8 lg:bottom-8",
          )}
        >
          <span className="relative flex size-7 items-center justify-center rounded-full bg-primary text-on-primary">
            {live && <span className="absolute inset-0 animate-ping rounded-full bg-primary/60 motion-reduce:hidden" aria-hidden />}
            <AudioLines className="relative size-4" aria-hidden />
          </span>
          <span className="text-sm font-medium">{live ? tr("copy.in_conversation_a418a55") : tr("copy.ask_adapt_07a99fc")}</span>
        </motion.button>
      )}
    </AnimatePresence>
  );
}

/**
 * The assistant's home in the shell: a docked, non-modal panel on the right on desktop (you
 * can keep working while you talk), a tall bottom sheet on phones.
 */
export function AssistantDock() {
  useLocale();
  const open = useUiStore((s) => s.assistantOpen);
  const setOpen = useUiStore((s) => s.setAssistantOpen);
  const desktop = useIsDesktop();
  const { pathname } = useLocation();
  const panelRef = useRef<HTMLElement>(null);
  const onAssistantPage = pathname === "/assistant";

  useEffect(() => {
    if (onAssistantPage && open) setOpen(false);
  }, [onAssistantPage, open, setOpen]);

  useEffect(() => {
    if (open && desktop) panelRef.current?.focus();
  }, [open, desktop]);

  if (onAssistantPage) return null;

  if (!desktop) {
    return (
      <Sheet open={open} onClose={() => setOpen(false)} title={tr("copy.adapt_assistant_054045a")} tall mobileOnly hideHeader bare>
        <AssistantPanel variant="sheet" onClose={() => setOpen(false)} />
      </Sheet>
    );
  }

  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.aside
          ref={panelRef}
          tabIndex={-1}
          aria-label={tr("copy.adapt_assistant_054045a")}
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 420, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.28, ease: [0.2, 0, 0, 1] }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
          }}
          className="sticky top-0 hidden h-dvh shrink-0 overflow-hidden border-s border-line bg-surface focus:outline-none lg:block"
        >
          <div className="flex h-full w-[420px] flex-col">
            <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
              <AudioLines className="size-5 text-primary" aria-hidden />
              <h2 className="flex-1 text-base">{tr("copy.adapt_assistant_054045a")}</h2>
              <Link
                to="/assistant"
                onClick={() => setOpen(false)}
                className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-sunken hover:text-ink"
                aria-label={tr("copy.open_full_screen_215ce5d")}
                title={tr("copy.open_full_screen_215ce5d")}
              >
                <Maximize2 className="size-4" aria-hidden />
              </Link>
              <IconButton label={tr("copy.close_the_assistant_0cb1fb8")} size="sm" onClick={() => setOpen(false)}>
                <X className="size-5" aria-hidden />
              </IconButton>
            </div>
            <div className="min-h-0 flex-1">
              <AssistantPanel variant="dock" />
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
