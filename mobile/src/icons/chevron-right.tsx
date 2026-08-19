import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgChevronRight = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    {...props}
  >
    <Path d="M6 12L10 8L6 4" strokeLinecap="round" strokeLinejoin="round" />
  </Svg>
);

export default SvgChevronRight;
