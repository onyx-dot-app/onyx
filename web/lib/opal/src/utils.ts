import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { RichStr } from "@opal/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Wraps strings for inline markdown parsing by `Text` and other Opal components.
 *
 * Multiple arguments are joined with newlines, so each string renders on its own line:
 * ```tsx
 * markdown("Line one", "Line two", "Line three")
 * ```
 */
export function markdown(...lines: string[]): RichStr {
  return { __brand: "RichStr", raw: lines.join("\n") };
}
