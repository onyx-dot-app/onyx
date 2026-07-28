import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgX = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 28 28"
    fill="none"
    stroke="currentColor"
    strokeWidth={2.5}
    {...props}
  >
    <Path d="M21 7L7 21M7 7L21 21" strokeLinejoin="round" />
  </Svg>
);

export default SvgX;
