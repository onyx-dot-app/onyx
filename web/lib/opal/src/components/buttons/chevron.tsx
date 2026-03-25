import "@opal/components/buttons/chevron.css";
import type { IconProps } from "@opal/types";
import { SvgChevronDownSmall } from "@opal/icons";
import { cn } from "@opal/utils";

/**
 * Chevron icon that rotates 180° when its parent `.interactive` enters
 * hover / active state.  Shared by OpenButton, FilterButton, and any
 * future button that needs an animated dropdown indicator.
 *
 * Stable component identity — never causes React to remount the SVG.
 */
function ChevronIcon({ className, ...props }: IconProps) {
  return (
    <SvgChevronDownSmall
      className={cn(className, "opal-button-chevron")}
      {...props}
    />
  );
}

export { ChevronIcon };
