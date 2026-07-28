import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgHashSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M5 6.5H6.5M11 6.5H9.5M5 9.5H6.5M11 9.5H9.5M6.5 5V6.5M6.5 11V9.5M9.5 5V6.5M9.5 11V9.5M6.5 9.5H9.5M6.5 9.5V6.5M9.5 9.5V6.5M9.5 6.5H6.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgHashSmall;
