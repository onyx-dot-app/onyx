import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/search-menu.tsx (stroke-based, viewBox 16).
/** Magnifying glass with menu lines / search menu. */
function SvgSearchMenu(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M1.00261 7.5H2.5M1 4H3.25M1.00261 11H3.25M15 13L12.682 10.682M12.682 10.682C13.4963 9.86764 14 8.74264 14 7.5C14 5.01472 11.9853 3 9.49999 3C7.01472 3 5 5.01472 5 7.5C5 9.98528 7.01472 12 9.49999 12C10.7426 12 11.8676 11.4963 12.682 10.682Z"
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

export { SvgSearchMenu };
