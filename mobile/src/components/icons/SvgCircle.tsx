import { Circle } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web circle icon.
function SvgCircle(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Circle cx={8} cy={8} r={4} stroke={color} strokeWidth={1.5} fill="none" />
      )}
    </Icon>
  );
}

export { SvgCircle };
