import { tr, localize, useLocale } from "@/i18n";
import { CalendarX2, Check, FlaskConical, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Segmented, Slider } from "@/components/ui/Controls";
import { Select, TextInput } from "@/components/ui/Field";
import { ProgressBar } from "@/components/ui/Progress";
import { hasChildren, HOUSEHOLD_LABEL, type Household } from "@/domain/profile";
import type { SimulationProgress } from "@/domain/simulate";
import { cn } from "@/lib/cn";
import {
  BUDGET,
  changedKeys,
  formatBudget,
  JURISDICTION_LABEL,
  PRESETS,
  presetActive,
  presetAvailable,
  togglePreset,
  variableValueLabel,
  VARIABLE_LABEL,
  type Draft,
  type VariableKey,
} from "./model";

const HOUSEHOLDS = Object.keys(HOUSEHOLD_LABEL) as Household[];

function Variable({
  id,
  name,
  changed,
  was,
  onReset,
  children,
}: {
  id: string;
  name: string;
  changed: boolean;
  was: string;
  onReset: () => void;
  children: ReactNode;
}) {
  useLocale();
  return (
    <div className={cn("flex flex-col gap-2.5 border-s-2 py-4 ps-4 pe-1 transition-colors", changed ? "border-primary" : "border-transparent")}>
      <div className="flex min-h-6 items-center gap-2">
        <span id={id} className="text-sm font-medium">
          {localize(name)}
        </span>
        {changed && <Badge tone="primary">{tr("copy.changed_cb5424f")}</Badge>}
        {changed && (
          <button
            type="button"
            onClick={onReset}
            className="ms-auto inline-flex min-h-8 items-center gap-1 rounded px-1 text-xs text-muted hover:text-ink"
            aria-label={localize(tr("copy.undo_the_change_to_v0_da11a05", { v0: name.toLowerCase() }))}
          >
            <RotateCcw className="size-3.5" aria-hidden />
            {tr("copy.undo_39fc721")}</button>
        )}
      </div>
      {localize(children)}
      {changed && <p className="text-xs text-muted">{tr("copy.in_your_plan_483279f")}{localize(was)}</p>}
    </div>
  );
}

export function VariablesPanel({
  base,
  draft,
  onChange,
  onRun,
  onCancel,
  running,
  progress,
  supported,
  className,
}: {
  base: Draft;
  draft: Draft;
  onChange: (draft: Draft) => void;
  onRun: () => void;
  onCancel: () => void;
  running: boolean;
  progress: SimulationProgress | null;
  /** What the simulation can change for this plan; the rest isn't offered. */
  supported: Set<VariableKey>;
  className?: string;
}) {
  useLocale();
  const changed = new Set(changedKeys(base, draft));
  const count = changed.size;
  const set = <K extends VariableKey>(key: K, value: Draft[K]) => onChange({ ...draft, [key]: value });
  const reset = (key: VariableKey) =>
    onChange({
      ...draft,
      [key]: base[key],
      ...(key === "household" ? { childrenCount: base.childrenCount } : {}),
    });
  // Where a company is licensed only matters while there is a company.
  const offered = (key: VariableKey) => supported.has(key) && !(key === "jurisdiction" && draft.companyTiming === "none");
  const variable = (key: VariableKey, children: ReactNode) =>
    offered(key) && (
    <Variable id={`var-${key}`} name={VARIABLE_LABEL[key]} changed={changed.has(key)} was={variableValueLabel(key, base)} onReset={() => reset(key)}>
      {localize(children)}
    </Variable>
  );
  const today = new Date();
  const presets = PRESETS.filter((preset) => offered(preset.key));

  return (
    <Card tone="raised" className={cn("@container/vars flex flex-col", className)}>
      <div className="shrink-0 px-5 pt-5">
        <h2 className="text-lg">{tr("copy.change_something_93f99fd")}</h2>
        <p className="mt-1 text-sm text-muted">{tr("copy.start_from_a_quick_change_or_set_your_own_your_p_bce898d")}</p>
      </div>

      <div className="flex flex-col">
        <div className="px-5 pt-4" role="group" aria-labelledby="quick-starts">
          <h3 id="quick-starts" className="mb-2 font-sans text-xs font-medium text-muted">
            {tr("copy.quick_starts_7912f8f")}</h3>
          <div className="flex flex-wrap gap-2">
            {presets.map((preset) => {
              const available = presetAvailable(base, preset, today);
              const active = presetActive(base, draft, preset, today);
              return (
                <button
                  key={preset.id}
                  type="button"
                  aria-pressed={active}
                  disabled={!available || running}
                  title={available ? preset.description : tr("copy.already_part_of_your_plan_8ffdc74")}
                  onClick={() => onChange(togglePreset(base, draft, preset, today))}
                  className={cn(
                    "inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                    active ? "border-primary bg-primary-tint font-medium text-primary-strong" : "border-line-strong bg-surface hover:border-ink/40",
                  )}
                >
                  {active && <Check className="size-3.5" aria-hidden />}
                  {localize(preset.label)}
                </button>
              );
            })}
          </div>
        </div>

        <fieldset disabled={running} className="mt-1 flex flex-col divide-y divide-line px-2">
          <legend className="sr-only">{tr("copy.variables_ac018db")}</legend>
          {localize(variable(
            "household",
            <div role="radiogroup" aria-labelledby="var-household" className="grid gap-1 @xl/vars:grid-cols-2">
              {HOUSEHOLDS.map((value) => (
                <label
                  key={value}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center gap-3 rounded-md border px-3 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus",
                    draft.household === value ? "border-ink bg-surface font-medium" : "border-line hover:border-line-strong",
                  )}
                >
                  <input
                    type="radio"
                    name="household"
                    value={value}
                    checked={draft.household === value}
                    onChange={() => set("household", value)}
                    className="sr-only"
                  />
                  <span
                    aria-hidden
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded-full border-2",
                      draft.household === value ? "border-ink" : "border-line-strong",
                    )}
                  >
                    {draft.household === value && <span className="size-2 rounded-full bg-ink" />}
                  </span>
                  {localize(HOUSEHOLD_LABEL[value])}
                  {base.household === value && <span className="ms-auto text-2xs font-normal text-subtle">{tr("copy.your_plan_b96ddaa")}</span>}
                </label>
              ))}
            </div>,
          ))}
          {hasChildren(draft.household) &&
            variable(
              "childrenCount",
              <Select
                aria-labelledby="var-childrenCount"
                value={String(Math.max(1, draft.childrenCount))}
                onChange={(e) => set("childrenCount", Number(e.target.value))}
              >
                {[1, 2, 3, 4, 5, 6].map((n) => (
                  <option key={n} value={n}>
                    {localize(n)} {n === 1 ? tr("copy.child_0e93069") : tr("copy.children_42685f1")}
                  </option>
                ))}
              </Select>,
            )}
          {localize(variable(
            "companyTiming",
            <Segmented
              label={localize(VARIABLE_LABEL.companyTiming)}
              value={draft.companyTiming}
              onChange={(value) => set("companyTiming", value)}
              className="w-full [&>*]:flex-1 [&>*]:justify-center"
              options={[
                { value: "now", label: tr("copy.start_now_67a04c7") },
                { value: "later", label: "Later" },
                { value: "none", label: tr("copy.no_company_5f4283d") },
              ]}
            />,
          ))}
          {localize(variable(
            "jurisdiction",
            <Segmented
              label={localize(VARIABLE_LABEL.jurisdiction)}
              // Nothing is selected while the plan hasn't decided.
              value={draft.jurisdiction}
              onChange={(value) => set("jurisdiction", value)}
              className="w-full [&>*]:flex-1 [&>*]:justify-center"
              options={[
                { value: "mainland", label: JURISDICTION_LABEL.mainland },
                { value: "adgm", label: JURISDICTION_LABEL.adgm },
              ]}
            />,
          ))}
          {localize(variable(
            "arrivalDate",
            <div className="flex items-center gap-2">
              <TextInput
                type="date"
                aria-labelledby="var-arrivalDate"
                value={draft.arrivalDate ?? ""}
                onChange={(e) => set("arrivalDate", e.target.value || null)}
                className="tabular flex-1"
              />
              {draft.arrivalDate && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-10"
                  onClick={() => set("arrivalDate", null)}
                  icon={<CalendarX2 className="size-4" aria-hidden />}
                >
                  {tr("copy.flexible_8bb749a")}</Button>
              )}
            </div>,
          ))}
          {localize(variable(
            "budget",
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className={cn("tabular text-base font-medium", draft.budget === null && "text-subtle")} aria-live="polite">
                  {localize(formatBudget(draft.budget))}
                </span>
                {draft.budget !== null && (
                  <button
                    type="button"
                    onClick={() => set("budget", null)}
                    className="min-h-8 text-xs text-muted underline-offset-4 hover:text-ink hover:underline"
                  >
                    {tr("copy.clear_719ea39")}</button>
                )}
              </div>
              <div className={cn(draft.budget === null && "opacity-60")}>
                <Slider
                  label={localize(VARIABLE_LABEL.budget)}
                  valueText={localize(formatBudget(draft.budget))}
                  value={draft.budget ?? BUDGET.min}
                  min={BUDGET.min}
                  max={BUDGET.max}
                  step={BUDGET.step}
                  onChange={(value) => set("budget", value)}
                />
              </div>
              <div className="tabular flex justify-between text-2xs text-subtle" aria-hidden>
                <span>{tr("copy.aed_3_000_ba578d6")}</span>
                <span>{tr("copy.aed_30_000_b5044c9")}</span>
              </div>
            </div>,
          ))}
          {localize(variable(
            "housing",
            <Segmented
              label={localize(VARIABLE_LABEL.housing)}
              value={draft.housing}
              onChange={(value) => set("housing", value)}
              className="w-full [&>*]:flex-1 [&>*]:justify-center"
              options={[
                { value: "long_lease", label: tr("copy.long_lease_1ebb24f") },
                { value: "short_stay_first", label: tr("copy.short_stay_first_c975bfa") },
              ]}
            />,
          ))}
        </fieldset>
      </div>

      {/* On desktop, Run stays in view at the bottom of the window while the variables scroll. */}
      <div className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-20 shrink-0 rounded-b-xl border-t border-line bg-surface/95 px-5 py-4 backdrop-blur-sm lg:bottom-0">
        {running ? (
          <div className="flex flex-col gap-3" aria-live="polite">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">
                <span className="font-medium">{tr("copy.simulating_a0d629d")}</span>
                {localize(progress?.label ?? tr("copy.starting_7725e05"))}
              </span>
              <Button variant="ghost" size="sm" onClick={onCancel}>
                {tr("copy.cancel_77dfd21")}</Button>
            </div>
            <ProgressBar value={progress?.progress ?? 0} label={tr("copy.simulation_progress_25cef5a")} />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted" aria-live="polite">
              {count === 0 ? tr("copy.change_something_above_to_compare_it_with_your_p_c87a263") : tr("copy.v0_v1_from_your_plan_c15c4c1", { v0: count, v1: count === 1 ? "change" : "changes" })}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={onRun} disabled={count === 0} icon={<FlaskConical className="size-4" aria-hidden />}>
                {tr("copy.run_simulation_3a51dd0")}</Button>
              {count > 0 && (
                <Button variant="ghost" onClick={() => onChange(base)}>
                  {tr("copy.reset_all_a21b0fe")}</Button>
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
