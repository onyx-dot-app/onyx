"use client";

import "@opal/components/tooltip/styles.css";
import { useRef, useState } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { RichStr } from "@opal/types";
import { Text } from "@opal/components";
import { isRichStr } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Which side of the trigger the tooltip appears on. `start` and `end` are
 * logical: in a right-to-left layout `start` is the right side.
 */
type TooltipSide = "top" | "bottom" | "start" | "end";
/**
 * Where the tooltip sits along its side. `follow` slides it to stay level
 * with the pointer: vertically for `start`/`end` sides, horizontally for
 * `top`/`bottom`. For a tall or wide trigger, such as a block of items.
 */
type TooltipAlign = "start" | "center" | "end" | "follow";

interface TooltipProps {
  /**
   * Tooltip content shown on hover. When `undefined`, the tooltip is not
   * rendered and children are returned as-is.
   *
   * - `string` or `RichStr` — rendered via `Text` with consistent styling.
   * - `ReactNode` — rendered as-is for custom tooltip content.
   */
  tooltip?: React.ReactNode | RichStr;

  /** Which side the tooltip appears on. @default "end" */
  side?: TooltipSide;

  /** Alignment along the tooltip's side axis. @default "center" */
  align?: TooltipAlign;

  /**
   * Shows nothing on hover, but keeps the trigger in place.
   *
   * Use this when the children hold state that is tied to the node: a ref
   * that a measurement reads, a running animation, or focus. Dropping
   * `tooltip` instead returns `children` bare, and the change of tree shape
   * remounts them.
   */
  suppressed?: boolean;

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
// Direction
// ---------------------------------------------------------------------------

/** Whether the page reads right to left. The root layout sets `dir`. */
function isRtl(): boolean {
  return (
    typeof document !== "undefined" && document.documentElement.dir === "rtl"
  );
}

/** Radix positions by physical side, so `start` and `end` follow `dir`. */
function physicalSide(side: TooltipSide): "top" | "bottom" | "left" | "right" {
  if (side === "top" || side === "bottom") return side;
  return (side === "start") !== isRtl() ? "left" : "right";
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
 * Hover is Radix's to track. There is deliberately no controlled `open`: Radix
 * drops any open change that already matches the value it was given, so a
 * caller that gates `open` on something other than the hover state stops
 * hearing about closes and holds a hover that ended. Use `suppressed` to turn
 * a tooltip off instead.
 *
 * @example
 * ```tsx
 * import { Tooltip } from "@opal/components";
 *
 * <Tooltip tooltip="Delete this item">
 *   <Button icon={SvgTrash} />
 * </Tooltip>
 *
 * // Off for now, but the trigger stays put
 * <Tooltip tooltip="Rename" suppressed={!isCollapsed}>
 *   <Button icon={SvgEdit} />
 * </Tooltip>
 * ```
 */
function Tooltip({
  tooltip,
  side = "end",
  align = "center",
  suppressed,
  delayDuration,
  sideOffset = 4,
  children,
}: TooltipProps) {
  // With `align="follow"`: the pointer's distance from the trigger's start
  // along the side's axis, and the tooltip's size on that axis.
  const [pointerOffset, setPointerOffset] = useState<number | null>(null);
  const [contentSize, setContentSize] = useState<number>(0);
  const contentRef = useRef<HTMLDivElement>(null);
  const alongY: boolean = side === "start" || side === "end";

  if (tooltip == null) return children;

  function trackPointer(event: React.PointerEvent<HTMLElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    // Measured from the trigger's start edge, which `align="start"` uses.
    setPointerOffset(
      alongY
        ? event.clientY - rect.top
        : isRtl()
          ? rect.right - event.clientX
          : event.clientX - rect.left
    );
    const content = contentRef.current;
    if (content) {
      setContentSize(alongY ? content.offsetHeight : content.offsetWidth);
    }
  }

  // Aligned to the trigger's start, then moved so the tooltip's middle
  // meets the pointer. Radix still shifts it back into view at an edge.
  const following: boolean = align === "follow" && pointerOffset !== null;

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
      delayDuration={delayDuration}
      /* Radix closes on a pointer that leaves the trigger from the content
      itself, which tracks the pointer across the gap between the two. A
      suppressed tooltip renders no content, so the trigger has to do the
      closing. Without this the tooltip stays open in Radix's eyes, and it
      appears the moment the suppression lifts. */
      disableHoverableContent={suppressed}
    >
      <TooltipPrimitive.Trigger
        asChild
        onPointerMove={align === "follow" ? trackPointer : undefined}
      >
        {children}
      </TooltipPrimitive.Trigger>
      {!suppressed && (
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            /* Dark surface in both themes, so the content resolves dark tokens. */
            ref={contentRef}
            className="dark opal-tooltip"
            side={physicalSide(side)}
            // Until the pointer moves, a follower sits centered.
            align={following ? "start" : align === "follow" ? "center" : align}
            alignOffset={
              following ? (pointerOffset ?? 0) - contentSize / 2 : undefined
            }
            sideOffset={sideOffset}
          >
            {content}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      )}
    </TooltipPrimitive.Root>
  );
}

export { Tooltip, type TooltipProps, type TooltipSide, type TooltipAlign };
