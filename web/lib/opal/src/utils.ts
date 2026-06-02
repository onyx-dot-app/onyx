import type { MutableRefObject, Ref, RefCallback } from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import copy from "copy-to-clipboard";
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

export function mergeRefs<T>(...refs: (Ref<T> | undefined)[]): RefCallback<T> {
  return (node: T | null) => {
    refs.forEach((ref) => {
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        (ref as MutableRefObject<T | null>).current = node;
      }
    });
  };
}

/**
 * Copies plain text to the clipboard.
 * Prefers the modern `navigator.clipboard` API and falls back to
 * `copy-to-clipboard` for environments where it is unavailable.
 */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  } else if (!copy(text)) {
    throw new Error("Failed to copy to clipboard");
  }
}
