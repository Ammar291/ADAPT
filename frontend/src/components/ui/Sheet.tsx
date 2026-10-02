import { tr, localize, useLocale } from "@/i18n";
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { IconButton } from "./Button";

/**
 * Modal sheet built on the native <dialog> (focus trapping, Escape, inert background).
 * Bottom sheet on small screens; end-side drawer from `md` up (mirrors in RTL), unless
 * `mobileOnly` keeps it a bottom sheet everywhere.
 */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  tall = false,
  mobileOnly = false,
  hideHeader = false,
  bare = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Use more of the screen height on phones (e.g. the assistant). */
  tall?: boolean;
  mobileOnly?: boolean;
  /** Visually hide the header (it stays available to screen readers). */
  hideHeader?: boolean;
  /** No body padding or scrolling: the content manages its own layout. */
  bare?: boolean;
}) {
  useLocale();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="adapt-sheet"
      data-mobile-only={mobileOnly || undefined}
      aria-labelledby={titleId}
      aria-describedby={description && !hideHeader ? descriptionId : undefined}
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose(); // backdrop click
      }}
    >
      <div
        className={cn(
          "adapt-sheet-panel flex flex-col bg-surface shadow-overlay",
          tall ? "h-[92dvh]" : "max-h-[88dvh]",
          !mobileOnly && "md:h-dvh md:max-h-none",
        )}
      >
        <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-line-strong md:hidden" aria-hidden />
        {hideHeader ? (
          <h2 id={titleId} className="sr-only">
            {localize(title)}
          </h2>
        ) : (
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <h2 id={titleId} className="text-lg">
                {localize(title)}
              </h2>
              {description && <p id={descriptionId} className="mt-0.5 text-sm text-muted">{localize(description)}</p>}
            </div>
            <IconButton label={tr("copy.close_bbfa773")} size="sm" onClick={onClose}>
              <X className="size-5" aria-hidden />
            </IconButton>
          </div>
        )}
        <div className={cn("relative min-h-0 flex-1", bare ? "flex flex-col" : "overflow-y-auto overscroll-contain px-5 pt-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]")}>{localize(children)}</div>
        {footer && <div className="shrink-0 border-t border-line px-5 pt-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">{localize(footer)}</div>}
      </div>
    </dialog>
  );
}
