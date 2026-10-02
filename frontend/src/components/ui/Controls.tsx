import { tr, localize, useLocale } from "@/i18n";
/**
 * Accessible interactive primitives built on Radix: segmented control, switch, slider,
 * tooltip and tabs, styled with ADAPT tokens.
 */
import { Slider as RadixSlider, Switch as RadixSwitch, Tabs as RadixTabs, ToggleGroup, Tooltip as RadixTooltip } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

// --- segmented control -------------------------------------------------------------------

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  count?: number;
  icon?: ReactNode;
}

/** One-of-many choice shown as connected buttons (arrow keys move between options). */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SegmentOption<T>[];
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  useLocale();
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(next) => next && onChange(next as T)}
      aria-label={localize(label)}
      className={cn("inline-flex max-w-full gap-1 overflow-x-auto rounded-lg bg-sunken p-1 scrollbar-none", className)}
    >
      {options.map((option) => (
        <ToggleGroup.Item
          key={option.value}
          value={option.value}
          className={cn(
            "adapt-segment inline-flex shrink-0 items-center gap-1.5 rounded-md font-medium whitespace-nowrap text-muted transition-colors",
            "hover:text-ink data-[state=on]:bg-surface data-[state=on]:text-ink data-[state=on]:shadow-card",
            size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-sm",
          )}
        >
          {localize(option.icon)}
          {localize(option.label)}
          {option.count !== undefined && (
            <span className="tabular rounded-full bg-sunken px-1.5 text-2xs text-subtle" aria-label={localize(tr("common.items", { count: option.count }))}>
              {localize(option.count)}
            </span>
          )}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

// --- switch ---------------------------------------------------------------------------------

export function Switch({
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
  id,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  id?: string;
}) {
  useLocale();
  return (
    <label className={cn("flex cursor-pointer items-start justify-between gap-4", disabled && "cursor-not-allowed opacity-60")}>
      <span className="min-w-0">
        <span className="block text-sm font-medium">{localize(label)}</span>
        {description && <span className="mt-0.5 block text-sm text-muted">{localize(description)}</span>}
      </span>
      <RadixSwitch.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      className="adapt-switch relative mt-0.5 h-6 w-10 shrink-0 rounded-full bg-line-strong transition-colors data-[state=checked]:bg-primary"
      >
        <RadixSwitch.Thumb className="block size-5 translate-x-0.5 rounded-full bg-surface shadow-card transition-transform data-[state=checked]:translate-x-[18px] rtl:data-[state=checked]:-translate-x-[18px]" />
      </RadixSwitch.Root>
    </label>
  );
}

// --- slider ---------------------------------------------------------------------------------

export function Slider({
  value,
  onChange,
  min,
  max,
  step,
  label,
  valueText,
}: {
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  label: string;
  valueText?: string;
}) {
  useLocale();
  return (
    <RadixSlider.Root
      value={[value]}
      onValueChange={(v) => onChange(v[0] ?? value)}
      min={min}
      max={max}
      step={step}
      className="relative flex h-6 w-full touch-none items-center select-none"
    >
      <RadixSlider.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-sunken">
        <RadixSlider.Range className="absolute h-full bg-primary" />
      </RadixSlider.Track>
      <RadixSlider.Thumb
        aria-label={localize(label)}
        aria-valuetext={valueText}
        className="block size-5 rounded-full border-2 border-primary bg-surface shadow-card focus-visible:ring-4 focus-visible:ring-primary/20 focus-visible:outline-none"
      />
    </RadixSlider.Root>
  );
}

// --- tooltip --------------------------------------------------------------------------------

export function TooltipProvider({ children }: { children: ReactNode }) {
  useLocale();
  return <RadixTooltip.Provider delayDuration={300}>{localize(children)}</RadixTooltip.Provider>;
}

/** Supplementary hint on hover or focus. Never the only place information lives. */
export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  useLocale();
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{localize(children)}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-ink px-2.5 py-1.5 text-xs text-canvas shadow-overlay"
        >
          {localize(content)}
          <RadixTooltip.Arrow className="fill-ink" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

// --- tabs -------------------------------------------------------------------------------------

export const Tabs = RadixTabs.Root;
export const TabsContent = RadixTabs.Content;

export function TabsList({ children, label, className }: { children: ReactNode; label: string; className?: string }) {
  useLocale();
  return (
    <RadixTabs.List aria-label={localize(label)} className={cn("flex gap-1 overflow-x-auto border-b border-line scrollbar-none", className)}>
      {localize(children)}
    </RadixTabs.List>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  useLocale();
  return (
    <RadixTabs.Trigger
      value={value}
      className="relative -mb-px inline-flex min-h-11 shrink-0 items-center gap-2 border-b-2 border-transparent px-3 text-sm font-medium text-muted transition-colors hover:text-ink data-[state=active]:border-primary data-[state=active]:text-primary-strong"
    >
      {localize(children)}
    </RadixTabs.Trigger>
  );
}
