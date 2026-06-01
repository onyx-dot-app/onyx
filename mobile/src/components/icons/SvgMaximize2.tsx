import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web maximize-2 icon.
/** Maximize / expand (two diagonal arrows). */
function SvgMaximize2(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M10 2H14M14 2V6M14 2L9.33333 6.66667M6 14H2M2 14V10M2 14L6.66667 9.33333"
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

export { SvgMaximize2 };
