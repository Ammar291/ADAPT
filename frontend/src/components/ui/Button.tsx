import { localize, useLocale } from "@/i18n";
import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
import { cn } from "@/lib/cn";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary:
    "bg-primary text-on-primary hover:bg-primary-strong disabled:bg-line-strong disabled:text-muted",
  secondary:
    "bg-surface text-ink border border-line-strong hover:border-ink/40 hover:bg-sunken disabled:text-subtle",
  ghost: "text-ink hover:bg-sunken disabled:text-subtle",
  danger: "bg-danger text-white hover:opacity-90 disabled:opacity-50",
};

const sizes: Record<Size, string> = {
  sm: "min-h-9 px-3 text-sm gap-1.5 rounded-lg",
  md: "min-h-11 px-4 text-sm gap-2 rounded-lg",
  lg: "h-12 px-5 text-base gap-2 rounded-lg",
};

/** Button styling for elements that must be links (e.g. router `<Link>`). */
export function buttonClass(variant: Variant = "primary", size: Size = "md", className?: string): string {
  return cn(
    "adapt-button inline-flex max-w-full select-none items-center justify-center text-center font-medium",
    "transition-colors duration-150",
    variants[variant],
    sizes[size],
    className,
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  useLocale();
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "adapt-button inline-flex max-w-full select-none items-center justify-center text-center font-medium",
        "transition-colors duration-150 disabled:cursor-not-allowed",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {loading ? <Spinner className="size-4" /> : icon}
      {localize(children)}
    </button>
  );
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: "sm" | "md";
  ref?: Ref<HTMLButtonElement>;
}

/** Square icon-only button. `label` is required: it becomes the accessible name. */
export function IconButton({ label, size = "md", className, children, type = "button", ...props }: IconButtonProps) {
  useLocale();
  return (
    <button
      type={type}
      aria-label={localize(label)}
      title={localize(label)}
      className={cn(
        "adapt-icon-button inline-flex shrink-0 items-center justify-center rounded-lg text-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
        "hover:bg-sunken hover:text-ink",
        size === "sm" ? "size-8" : "size-10",
        className,
      )}
      {...props}
    >
      {localize(children)}
    </button>
  );
}
