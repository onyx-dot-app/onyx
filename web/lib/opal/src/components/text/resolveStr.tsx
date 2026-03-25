import type { ReactNode } from "react";

import type { RichStr } from "@opal/types";
import InlineMarkdown from "@opal/components/text/InlineMarkdown";

function isRichStr(value: unknown): value is RichStr {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as RichStr).__brand === "RichStr"
  );
}

/**
 * Resolves a `string | RichStr` to a `ReactNode`.
 *
 * - `RichStr` → parsed inline markdown
 * - `string` → returned as-is
 *
 * Internal to Opal — not exported from the barrel.
 */
export function resolveStr(value: string | RichStr): ReactNode {
  return isRichStr(value) ? <InlineMarkdown content={value.raw} /> : value;
}

/**
 * Extracts the plain string from a `string | RichStr`.
 *
 * Useful when a plain `string` is required (e.g., HTML `title` attributes,
 * input default values).
 */
export function toPlainString(value: string | RichStr): string {
  return isRichStr(value) ? value.raw : value;
}

/**
 * Resolves a `ReactNode` that may contain a `RichStr`.
 *
 * Used by `Text` where children is `ReactNode` (not constrained to `string | RichStr`).
 */
export function resolveChildren(children: ReactNode): ReactNode {
  return isRichStr(children) ? (
    <InlineMarkdown content={children.raw} />
  ) : (
    children
  );
}
