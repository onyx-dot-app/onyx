import type { ReactNode } from "react";
import { Disabled } from "@opal/core";
import type { RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ReadOnlyRegionProps {
  /**
   * When `true`, the children are shown but cannot be used: dimmed, no
   * pointer, no focus, no keyboard. When `false`, the children render as they
   * are.
   * @default true
   */
  readOnly?: boolean;

  /**
   * Why the region is read-only, shown on hover. Supports inline markdown via
   * `markdown()`. Screen readers read it from a hidden live region.
   */
  tooltip?: string | RichStr;

  children?: ReactNode;
}

// ---------------------------------------------------------------------------
// ReadOnlyRegion
// ---------------------------------------------------------------------------

/**
 * A region of the page the user can see but not use: a whole settings page
 * on a plan that does not include it, a form while a request is pending.
 *
 * Built on `Disabled`, which dims the region, blocks the pointer and disables
 * the form controls inside. On top of that the region is `inert`, so the
 * browser also skips elements that are focusable without being form controls
 * (cards and rows with a key handler). Nothing inside can take focus, so no
 * popup or editor can open from it.
 *
 * @example
 * ```tsx
 * <ReadOnlyRegion readOnly={!planIncludesIt} tooltip="Available on Enterprise">
 *   <SettingsForm />
 * </ReadOnlyRegion>
 * ```
 */
export function ReadOnlyRegion({
  readOnly = true,
  tooltip,
  children,
}: ReadOnlyRegionProps) {
  return (
    <Disabled
      disabled={readOnly}
      inert={readOnly || undefined}
      tooltip={tooltip}
    >
      {children}
    </Disabled>
  );
}
