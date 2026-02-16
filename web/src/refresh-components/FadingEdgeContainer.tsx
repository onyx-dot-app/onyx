import React from "react";
import { cn } from "@/lib/utils";

interface FadingEdgeContainerProps {
  /** Classes applied to the inner scrollable container */
  className?: string;
  /** Classes to customize the fade gradient (e.g., height, color) */
  fadeClassName?: string;
  children: React.ReactNode;
  /** Which edge to show the fade on */
  direction?: "top" | "bottom";
}

/**
 * A container that adds a gradient fade overlay at the top or bottom edge.
 *
 * Use this component to wrap scrollable content where you want to visually
 * indicate that more content exists beyond the visible area. The fade stays
 * fixed relative to the container bounds, not the scroll content.
 *
 * @example
 * // Bottom fade for a scrollable list
 * <FadingEdgeContainer
 *   direction="bottom"
 *   className="max-h-[300px] overflow-y-auto"
 * >
 *   {items.map(item => <Item key={item.id} />)}
 * </FadingEdgeContainer>
 *
 * @example
 * // Top fade with custom fade styling
 * <FadingEdgeContainer
 *   direction="top"
 *   className="max-h-[200px] overflow-y-auto"
 *   fadeClassName="h-12"
 * >
 *   {content}
 * </FadingEdgeContainer>
 */
const FadingEdgeContainer: React.FC<FadingEdgeContainerProps> = ({
  className,
  fadeClassName,
  children,
  direction = "top",
}) => {
  const isTop = direction === "top";

  return (
    <div className="relative">
      <div className={className}>{children}</div>
      <div
        className={cn(
          "absolute inset-x-0 h-8 pointer-events-none z-10",
          isTop
            ? "top-0 bg-gradient-to-b from-background to-transparent"
            : "bottom-0 bg-gradient-to-t from-background to-transparent",
          fadeClassName
        )}
      />
    </div>
  );
};

export default FadingEdgeContainer;
