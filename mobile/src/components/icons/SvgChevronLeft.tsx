import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirror of SvgChevronRight (the Opal curated set has no left chevron); used as
// the back glyph in the actions popover's sources sub-view header (stroke-based,
// viewBox 16).
/** Chevron pointing left (back). */
function SvgChevronLeft(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M10 12L6 8L10 4"
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      )}
    </Icon>
  );
}

export { SvgChevronLeft };
