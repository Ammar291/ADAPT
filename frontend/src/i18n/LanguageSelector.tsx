import { Check, ChevronDown, Globe2 } from "lucide-react";
import { Popover } from "radix-ui";
import { useState } from "react";
import { useUpdatePreferences } from "@/lib/api/hooks";
import { toast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { setUiLocale, tr, useLocale } from ".";
import { getLanguage, uiLanguages } from "./registry";

export function LanguagePicker({ className, onSave }: { className?: string; onSave?: (code: string) => void }) {
  const locale = useLocale();
  const selected = getLanguage(locale)!;
  const [open, setOpen] = useState(false);

  async function choose(code: string) {
    setOpen(false);
    if (code !== locale) await setUiLocale(code); // immediate, including when offline
    onSave?.(code);
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger className={cn("inline-flex min-h-11 max-w-full items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-medium shadow-card transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus", className)} aria-label={tr("language.choose")}>
        <Globe2 className="size-4 shrink-0 text-primary" aria-hidden />
        <span className="truncate"><bdi lang={selected.code}>{selected.nativeName}</bdi><span className="ms-2 text-xs font-normal text-muted" lang="en">{selected.nativeName !== selected.englishName && selected.englishName}</span></span>
        <ChevronDown className="ms-auto size-3.5 text-subtle" aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} collisionPadding={16} className="z-50 w-[min(320px,calc(100vw-32px))] rounded-xl border border-line bg-surface p-2 text-ink shadow-overlay" aria-label={tr("language.choose")}>
          <p className="px-3 pt-2 pb-3 text-xs font-medium text-muted">{tr("language.interface")}</p>
          <div className="max-h-[min(420px,60dvh)] overflow-y-auto overscroll-contain" role="group" aria-label={tr("language.available")}>
            {uiLanguages.map((language) => <button key={language.code} type="button" onClick={() => void choose(language.code)} aria-pressed={language.code === locale} className={cn("flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-start hover:bg-sunken focus-visible:outline-2 focus-visible:outline-focus", language.code === locale && "bg-primary-tint")}>
              <span className="min-w-0 flex-1"><bdi className="block text-sm font-medium" lang={language.code}>{language.nativeName}</bdi><span className="block text-xs text-muted" lang="en">{language.englishName}</span></span>
              {language.code === locale && <Check className="size-4 text-primary" aria-hidden />}
            </button>)}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** Profile preference uses the existing authenticated service and serialized mutation queue. */
export function LanguageSelector({ className }: { className?: string }) {
  const mutation = useUpdatePreferences();
  return <LanguagePicker className={className} onSave={(code) => mutation.mutate({ uiLocale: code }, {
    onError: () => toast({ tone: "error", title: tr("language.savedOnDevice"), description: tr("language.syncFailed") }),
  })} />;
}
