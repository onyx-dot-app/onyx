import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web menu icon.
/** Hamburger menu (three lines). */
function SvgMenu(props: IconProps) {
  return (
    <Icon viewBox="0 0 32 32" {...props}>
      {({ color }) => (
        <Path
          d="M26.5 9H5.5M5.5 23H26.5M26.5 16H5.5"
          stroke={color}
          strokeWidth={2}
          strokeLinejoin="round"
          fill="none"
        />
      )}
    </Icon>
  );
}

export { SvgMenu };
