import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgTwoLineSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M6 6.50002V9.50002M10 6.50002V9.50002"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgTwoLineSmall;
