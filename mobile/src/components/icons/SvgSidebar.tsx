import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web sidebar icon.
function SvgSidebar(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M6 2V14M3.33333 2H12.6667C13.403 2 14 2.59695 14 3.33333V12.6667C14 13.403 13.403 14 12.6667 14H3.33333C2.59695 14 2 13.403 2 12.6667V3.33333C2 2.59695 2.59695 2 3.33333 2Z"
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

export { SvgSidebar };
