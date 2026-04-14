"use client";

import "@opal/components/tooltip/styles.css";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { RichStr } from "@opal/types";
import type { TooltipSide } from "@opal/components";
import { Text } from "@opal/components";
import { isRichStr } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TooltipProps {
  /**
   * Tooltip content shown on hover. When `undefined`, the tooltip is not
   * rendered and children are returned as-is.
   *
   * - `string` or `RichStr` — rendered via `Text` with consistent styling.
   * - `ReactNode` — rendered as-is for custom tooltip content.
   */
  tooltip?: React.ReactNode | RichStr;

  /** Which side the tooltip appears on. @default "right" */
  tooltipSide?: TooltipSide;

  /**
   * When `true`, suppresses the tooltip even if `tooltip` is defined.
   * Children are still rendered normally.
   * @default false
   */
  disabled?: boolean;

  /**
   * Delay in milliseconds before the tooltip appears on hover.
   * Passed to `TooltipPrimitive.Root`.
   */
  delayDuration?: number;

  /**
   * Children to wrap. Must be a single element compatible with Radix
   * `asChild` (i.e. a DOM element or a component that forwards refs).
   */
  children: React.ReactElement;
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

/**
 * A minimal tooltip wrapper that shows content on hover.
 *
 * Renders nothing extra when `tooltip` is `undefined` or `disabled` is
 * `true` — just passes children through. When `tooltip` is provided,
 * wraps children with a Radix tooltip.
 *
 * @example
 * ```tsx
 * import { Tooltip } from "@opal/components";
 *
 * <Tooltip tooltip="Delete this item">
 *   <Button icon={SvgTrash} />
 * </Tooltip>
 *
 * <Tooltip tooltip="Not available" disabled={isAvailable}>
 *   <Button icon={SvgTrash} />
 * </Tooltip>
 *
 * <Tooltip tooltip="Quick tooltip" delayDuration={0}>
 *   <span>Instant</span>
 * </Tooltip>
 * ```
 */
function Tooltip({
  tooltip,
  tooltipSide = "right",
  disabled = false,
  delayDuration,
  children,
}: TooltipProps) {
  if (!tooltip || disabled) return children;

  const content =
    typeof tooltip === "string" || isRichStr(tooltip) ? (
      <Text font="secondary-body" color="inherit">
        {tooltip}
      </Text>
    ) : (
      tooltip
    );

  return (
    <TooltipPrimitive.Root delayDuration={delayDuration}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="opal-tooltip"
          side={tooltipSide}
          sideOffset={4}
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { Tooltip, type TooltipProps };
