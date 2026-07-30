import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgChevronDown = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    {...props}
  >
    <Path d="M4 6L8 10L12 6" strokeLinecap="round" strokeLinejoin="round" />
  </Svg>
);

export default SvgChevronDown;
