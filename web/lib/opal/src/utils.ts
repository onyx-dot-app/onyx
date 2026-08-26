import type { MutableRefObject, ReactNode, Ref, RefCallback } from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import copy from "copy-to-clipboard";
import type { RichNodes, RichStr } from "@opal/types";

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

/**
 * Brands React nodes as deliberate `Text` children.
 *
 * Use for sentences that must embed inline components — the main case is
 * next-intl rich-text output:
 * ```tsx
 * <Text font="main-ui-body" color="text-04">
 *   {richNodes(t.rich("help.text", { link: (chunks) => <a ...>{chunks}</a> }))}
 * </Text>
 * ```
 * Do not use it to pass layout JSX into `Text`; the content must stay inline.
 */
export function richNodes(nodes: ReactNode): RichNodes {
  return { __brand: "RichNodes", nodes };
}

export function isRichNodes(value: unknown): value is RichNodes {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as RichNodes).__brand === "RichNodes"
  );
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

/**
 * Builds a keyboard handler that mirrors a click on Enter or Space.
 *
 * Pair this with `role="button"` and `tabIndex={0}` on containers that cannot
 * be a real `<button>` — usually because they wrap other interactive elements,
 * and nested buttons are invalid HTML.
 */
export function clickOnKeyDown(
  onClick: () => void
): (event: React.KeyboardEvent) => void {
  return (event: React.KeyboardEvent) => {
    // Keyboard events bubble, so a nested button would fire its own action and
    // this one. Only act when the container itself holds focus.
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    // A held key repeats, but a real <button> fires one click per press.
    if (event.repeat) return;
    event.preventDefault();
    onClick();
  };
}
