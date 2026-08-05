import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgBarChartSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M11 10.5V7M8 10.5V4.5M5 10.5V8"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgBarChartSmall;
