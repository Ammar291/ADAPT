import { tr, localize, useLocale } from "@/i18n";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  useLocale();
  return (
    <header className={cn("flex flex-col gap-4 pb-6 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 max-w-2xl">
        <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.16em] text-primary-strong">{tr("copy.your_abu_dhabi_workspace_f124757")}</p>
        <h1 className="text-2xl sm:text-3xl">{localize(title)}</h1>
        {description && <p className="mt-2 text-muted">{localize(description)}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{localize(actions)}</div>}
    </header>
  );
}
