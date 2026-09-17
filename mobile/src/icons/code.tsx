import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgCode = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M10.6667 12L14.6667 8L10.6667 4M5.33334 4L1.33334 8L5.33334 12"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgCode;
