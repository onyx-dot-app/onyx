import Svg, { Circle } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgCircle = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Circle cx={8} cy={8} r={4} strokeWidth={1.5} />
  </Svg>
);

export default SvgCircle;
