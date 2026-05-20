"use client";

import "@opal/components/tooltip/styles.css";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { RichStr } from "@opal/types";
import { Text } from "@opal/components";
import { isRichStr } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TooltipSide = "top" | "bottom" | "left" | "right";
type TooltipAlign = "start" | "center" | "end";

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
  side?: TooltipSide;

  /** Alignment along the tooltip's side axis. @default "center" */
  align?: TooltipAlign;

  /**
   * Controlled open state. When provided, the tooltip's visibility is
   * externally managed. When omitted, the tooltip uses Radix's default
   * hover-based open handling.
   */
  open?: boolean;

  /**
   * Callback fired when the tooltip's open state changes. Use with `open`
   * for controlled behavior.
   */
  onOpenChange?: (open: boolean) => void;

  /**
   * Delay in milliseconds before the tooltip appears on hover.
   * Passed to `TooltipPrimitive.Root`.
   */
  delayDuration?: number;

  /** Distance in pixels between the trigger and the tooltip. @default 4 */
  sideOffset?: number;

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
 * Renders nothing extra when `tooltip` is `undefined` — just passes children
 * through. When `tooltip` is provided, wraps children with a Radix tooltip.
 *
 * Supports both uncontrolled (default hover behavior) and controlled
 * (`open` + `onOpenChange`) modes.
 *
 * @example
 * ```tsx
 * import { Tooltip } from "@opal/components";
 *
 * // Uncontrolled (default)
 * <Tooltip tooltip="Delete this item">
 *   <Button icon={SvgTrash} />
 * </Tooltip>
 *
 * // Controlled
 * <Tooltip tooltip="Details" open={isOpen} onOpenChange={setIsOpen}>
 *   <Button icon={SvgInfo} />
 * </Tooltip>
 * ```
 */
function Tooltip({
  tooltip,
  side = "right",
  align = "center",
  open,
  onOpenChange,
  delayDuration,
  sideOffset = 4,
  children,
}: TooltipProps) {
  if (tooltip == null) return children;

  const content =
    typeof tooltip === "string" || isRichStr(tooltip) ? (
      <Text font="secondary-body" color="inherit" as="p">
        {tooltip}
      </Text>
    ) : (
      tooltip
    );

  return (
    <TooltipPrimitive.Root
      open={open}
      onOpenChange={onOpenChange}
      delayDuration={delayDuration}
    >
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="opal-tooltip"
          side={side}
          align={align}
          sideOffset={sideOffset}
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { Tooltip, type TooltipProps, type TooltipSide, type TooltipAlign };
