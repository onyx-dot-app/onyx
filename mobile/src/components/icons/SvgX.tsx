import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web x icon.
function SvgX(props: IconProps) {
  return (
    <Icon viewBox="0 0 28 28" {...props}>
      {({ color }) => (
        <Path
          d="M21 7L7 21M7 7L21 21"
          stroke={color}
          strokeWidth={2.5}
          strokeLinejoin="round"
          fill="none"
        />
      )}
    </Icon>
  );
}

export { SvgX };
