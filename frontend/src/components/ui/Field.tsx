import { tr, localize, useLocale } from "@/i18n";
import { ChevronDown } from "lucide-react";
import { useId, type InputHTMLAttributes, type ReactNode, type Ref, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const control =
  "w-full rounded-md border border-line-strong bg-surface text-sm text-ink placeholder:text-subtle transition-colors focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-danger";

/** Label, hint and error around one control, wired up for screen readers. */
export function Field({
  label,
  hint,
  error,
  children,
  className,
  optional,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
  className?: string;
  optional?: boolean;
}) {
  useLocale();
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {localize(label)}
        {optional && <span className="ms-1.5 font-normal text-subtle">{tr("copy.optional_b16c7ac")}</span>}
      </label>
      {localize(children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined }))}
      {hint && !error && (
        <p id={hintId} className="text-xs text-subtle">
          {localize(hint)}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-xs text-danger">
          {localize(error)}
        </p>
      )}
    </div>
  );
}

export function TextInput({ className, ref, ...props }: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  useLocale();
  return <input ref={ref} className={cn(control, "h-10 px-3", className)} {...props} />;
}

export function TextArea({ className, ref, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { ref?: Ref<HTMLTextAreaElement> }) {
  useLocale();
  return <textarea ref={ref} className={cn(control, "px-3 py-2.5 leading-relaxed", className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  useLocale();
  return (
    <div className="relative">
      <select className={cn(control, "h-10 appearance-none ps-3 pe-9", className)} {...props}>
        {localize(children)}
      </select>
      <ChevronDown className="pointer-events-none absolute end-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden />
    </div>
  );
}
