import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web chevron-right icon.
function SvgChevronRight(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M6 12L10 8L6 4"
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

export { SvgChevronRight };
