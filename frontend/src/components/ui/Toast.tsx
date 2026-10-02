import { tr, localize, useLocale } from "@/i18n";
import { CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { create } from "zustand";
import { cn } from "@/lib/cn";

type ToastTone = "success" | "info" | "error";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  action?: { label: string; to: string };
  /** Milliseconds; 0 keeps it until dismissed. */
  duration?: number;
  onDismiss?: () => void;
}

interface ToastItem extends ToastInput {
  id: number;
}

interface ToastState {
  toasts: ToastItem[];
  push: (toast: ToastInput) => number;
  dismiss: (id: number) => void;
}

let counter = 0;

const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push: (toast) => {
    const id = ++counter;
    set({ toasts: [...get().toasts.slice(-2), { ...toast, id }] });
    return id;
  },
  dismiss: (id) => {
    const toast = get().toasts.find((t) => t.id === id);
    toast?.onDismiss?.();
    set({ toasts: get().toasts.filter((t) => t.id !== id) });
  },
}));

/** Show a short confirmation, e.g. `toast({ title: "Approved" })`. */
export function toast(input: ToastInput): number {
  return useToastStore.getState().push(input);
}

const ICON: Record<ToastTone, typeof Info> = { success: CircleCheck, info: Info, error: TriangleAlert };

function ToastCard({ toast: item }: { toast: ToastItem }) {
  useLocale();
  const dismiss = useToastStore((s) => s.dismiss);
  const tone = item.tone ?? "success";
  const Icon = ICON[tone];
  const reducedMotion = useReducedMotion();
  const [paused, setPaused] = useState(false);
  const remaining = useRef(item.duration ?? (tone === "error" ? 8000 : 4500));
  useEffect(() => {
    if (paused || item.duration === 0) return;
    const started = Date.now();
    const timer = setTimeout(() => dismiss(item.id), remaining.current);
    return () => { clearTimeout(timer); remaining.current = Math.max(0, remaining.current - (Date.now() - started)); };
  }, [item.id, item.duration, dismiss, paused]);

  return (
    <motion.li
      role={tone === "error" ? "alert" : "status"}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setPaused(false); }}
      layout
      initial={reducedMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: reducedMotion ? 0 : 8, transition: { duration: reducedMotion ? 0 : 0.15 } }}
      className="pointer-events-auto flex w-full items-start gap-3 rounded-lg border border-line bg-surface p-3.5 shadow-overlay"
    >
      <Icon className={cn("mt-0.5 size-5 shrink-0", tone === "error" ? "text-danger" : tone === "info" ? "text-civic" : "text-primary")} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{localize(item.title)}</p>
        {item.description && <p className="mt-0.5 text-sm text-muted">{localize(item.description)}</p>}
        {item.action && (
          <Link
            to={item.action.to}
            onClick={() => dismiss(item.id)}
            className="mt-2 inline-block text-sm font-medium text-primary-strong underline underline-offset-4"
          >
            {localize(item.action.label)}
          </Link>
        )}
      </div>
      <button type="button" onClick={() => dismiss(item.id)} aria-label={tr("copy.dismiss_notification_dc83cd8")} className="adapt-icon-button -me-2 -mt-2 flex size-9 shrink-0 items-center justify-center rounded-lg text-subtle hover:bg-sunken hover:text-ink">
        <X className="size-4" aria-hidden />
      </button>
    </motion.li>
  );
}

/** Mounted once in the app shell. Announced politely to screen readers. */
export function Toaster() {
  useLocale();
  const toasts = useToastStore((s) => s.toasts);
  return (
    <ol
      aria-live="polite"
      aria-label={tr("copy.notifications_753a22b")}
      className="pointer-events-none fixed inset-x-4 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-[60] mx-auto flex max-w-sm flex-col gap-2 lg:inset-x-auto lg:end-6 lg:bottom-24 lg:w-96"
    >
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} />
        ))}
      </AnimatePresence>
    </ol>
  );
}
