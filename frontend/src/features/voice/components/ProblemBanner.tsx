import { tr, localize, useLocale } from "@/i18n";
import { AlertTriangle, Keyboard, RotateCw, X } from "lucide-react";
import { Button, IconButton } from "@/components/ui/Button";
import type { Mode, Problem } from "../conversation";

/** Says what went wrong with voice and what to do next. The conversation is never lost. */
export function ProblemBanner({
  problem,
  mode,
  onRetry,
  onType,
  onDismiss,
}: {
  problem: Problem;
  mode: Mode;
  onRetry: () => void;
  onType: () => void;
  onDismiss: () => void;
}) {
  useLocale();
  return (
    <div role="alert" className="mx-4 mb-3 flex gap-3 rounded-lg border border-danger/30 bg-danger-tint p-3">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{localize(problem.title)}</p>
        <p className="mt-0.5 text-sm text-muted">{localize(problem.detail)}</p>
        {(problem.canRetry || mode === "voice") && (
          <div className="mt-2 flex flex-wrap gap-2">
            {problem.canRetry && (
              <Button size="sm" variant="secondary" icon={<RotateCw className="size-4" aria-hidden />} onClick={onRetry}>
                {tr("copy.try_voice_again_e8e972b")}</Button>
            )}
            {mode === "voice" && (
              <Button size="sm" variant="secondary" icon={<Keyboard className="size-4" aria-hidden />} onClick={onType}>
                {tr("copy.type_instead_78a8fc4")}</Button>
            )}
          </div>
        )}
      </div>
      <IconButton label={tr("copy.dismiss_70afe9e")} size="sm" onClick={onDismiss}>
        <X className="size-4" aria-hidden />
      </IconButton>
    </div>
  );
}
