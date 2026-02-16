/**
 * SimpleTooltip - A wrapper component for easily adding tooltips to elements.
 *
 * IMPORTANT: Children must be ref-compatible (either a DOM element or a component
 * that uses forwardRef). This is required because TooltipTrigger uses `asChild`
 * which needs to attach a ref to the child element for positioning.
 *
 * Valid children:
 * - DOM elements: <div>, <button>, <span>, etc.
 * - forwardRef components: Components wrapped with React.forwardRef()
 *
 * Invalid children (will cause errors or warnings):
 * - Fragments: <>{content}</>
 * - Regular function components that don't forward refs
 * - Multiple children
 *
 * @example
 * // Valid - DOM element
 * <SimpleTooltip tooltip="Hello">
 *   <button>Hover me</button>
 * </SimpleTooltip>
 *
 * // Valid - forwardRef component
 * <SimpleTooltip tooltip="Card tooltip">
 *   <Card>Content</Card>
 * </SimpleTooltip>
 *
 * // Invalid - will cause React warning
 * <SimpleTooltip tooltip="Won't work">
 *   <NonForwardRefComponent />
 * </SimpleTooltip>
 */

"use client";

import React from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Text from "@/refresh-components/texts/Text";

export interface SimpleTooltipProps
  extends React.ComponentPropsWithoutRef<typeof TooltipContent> {
  disabled?: boolean;
  tooltip?: React.ReactNode;
  children?: React.ReactNode;
  delayDuration?: number;
}

export default function SimpleTooltip({
  disabled = false,
  tooltip,
  className,
  children,
  side = "right",
  delayDuration,
  ...rest
}: SimpleTooltipProps) {
  // Determine hover content based on the logic:
  // 1. If tooltip is defined, use tooltip
  // 2. If tooltip is undefined and children is a string, use children
  // 3. Otherwise, no tooltip
  const hoverContent =
    tooltip ?? (typeof children === "string" ? children : undefined);

  // If no hover content, just render children without tooltip
  if (!hoverContent) return children;

  // Check if tooltip is a string to wrap in Text component, otherwise render as-is
  const tooltipContent =
    typeof hoverContent === "string" ? (
      <Text as="p" textLight05>
        {hoverContent}
      </Text>
    ) : (
      hoverContent
    );

  return (
    <TooltipProvider delayDuration={delayDuration}>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        {!disabled && (
          <TooltipContent side={side} className={className} {...rest}>
            {tooltipContent}
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}
