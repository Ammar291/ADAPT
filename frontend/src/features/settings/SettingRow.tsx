import { tr, localize, useLocale } from "@/i18n";
import { Check } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";

/** A titled group of settings rows, divided by hairlines inside one quiet surface. */
export function SettingGroup({ title, description, children, id }: { title: string; description?: string; children: ReactNode; id: string }) {
  useLocale();
  return (
    <section aria-labelledby={id}>
      <div className="mb-3">
        <h2 id={id} className="text-base font-medium">
          {localize(title)}
        </h2>
        {description && <p className="mt-0.5 text-sm text-muted">{localize(description)}</p>}
      </div>
      <div className="divide-y divide-line rounded-lg border border-line bg-surface">{localize(children)}</div>
    </section>
  );
}

export type SaveState = "idle" | "saving" | "saved";

/**
 * One setting: what it is and what it does on the start side, the control on the end side
 * (stacked on phones). `state` announces saving politely next to the title.
 */
export function SettingRow({
  title,
  description,
  control,
  state = "idle",
  footer,
  titleId,
}: {
  title: string;
  description: ReactNode;
  control?: ReactNode;
  state?: SaveState;
  footer?: ReactNode;
  titleId?: string;
}) {
  useLocale();
  const fallbackId = useId();
  const id = titleId ?? fallbackId;
  return (
    <div className="flex flex-col gap-3 px-4 py-4 sm:px-5 md:flex-row md:items-start md:justify-between md:gap-8">
      <div className="min-w-0 md:max-w-md">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 id={id} className="font-sans text-sm font-medium">
            {localize(title)}
          </h3>
          <span aria-live="polite" className="inline-flex items-center gap-1.5 text-2xs text-muted">
            {state === "saving" && (
              <>
                <Spinner className="size-3.5 text-primary" />
                {tr("copy.saving_369c534")}</>
            )}
            {state === "saved" && (
              <>
                <Check className="size-3.5 text-primary" aria-hidden />
                {tr("copy.saved_c0ae8f6")}</>
            )}
          </span>
        </div>
        <div className="mt-1 text-sm text-muted">{localize(description)}</div>
        {localize(footer)}
      </div>
      {control && <div className="shrink-0 md:pt-0.5">{localize(control)}</div>}
    </div>
  );
}

export interface Option<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
}

/**
 * One-of-many choice as connected segments, built on native radios: arrow keys move the
 * choice, and each segment is at least 44px tall on phones.
 */
export function OptionGroup<T extends string>({
  name,
  value,
  options,
  onChange,
  labelledBy,
  disabled,
  className,
}: {
  name: string;
  value: T | "";
  options: Option<T>[];
  onChange: (value: T) => void;
  labelledBy: string;
  disabled?: boolean;
  className?: string;
}) {
  useLocale();
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} className={cn("flex w-full gap-1 rounded-lg bg-sunken p-1 md:inline-flex md:w-auto", className)}>
      {options.map((option) => (
        <label
          key={option.value}
          className={cn(
            "relative flex h-11 min-w-0 flex-auto cursor-pointer items-center justify-center gap-1.5 rounded-md px-3 text-sm font-medium whitespace-nowrap text-muted transition-colors md:h-9 md:flex-none [&>svg]:shrink-0",
            "hover:text-ink has-[:checked]:bg-surface has-[:checked]:text-ink has-[:checked]:shadow-card",
            "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus",
            disabled && "cursor-not-allowed opacity-60",
          )}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={disabled}
            onChange={() => onChange(option.value)}
            className="sr-only"
          />
          {localize(option.icon)}
          {localize(option.label)}
        </label>
      ))}
    </div>
  );
}
