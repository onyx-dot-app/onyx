import { cn } from "@opal/utils";
import { SvgChevronDown } from "@opal/icons";
import type { IconProps } from "@opal/types";

/**
 * The family's dropdown chevron: rotates open/closed with a transition.
 *
 * A stable component on purpose — an inline `icon={({className, ...}) => …}`
 * closing over the open state changes identity when the state flips, so
 * React remounts the icon and the transition never plays. Rotation is
 * driven instead by a `data-dropdown-open` attribute on a wrapping element,
 * which flips in place on the same DOM node.
 */
export function RotatingChevron({ className, ...props }: IconProps) {
  return (
    <SvgChevronDown
      {...props}
      className={cn(
        className,
        "transition-transform duration-200",
        "[[data-dropdown-open=true]_&]:rotate-180"
      )}
    />
  );
}
