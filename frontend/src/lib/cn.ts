import { clsx, type ClassValue } from "clsx";

/** Compose class names. Components own their variants, so no merge step is needed. */
export function cn(...values: ClassValue[]): string {
  return clsx(values);
}
