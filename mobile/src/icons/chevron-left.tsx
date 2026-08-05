import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgChevronLeft = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    {...props}
  >
    <Path d="M10 12L6 8L10 4" strokeLinecap="round" strokeLinejoin="round" />
  </Svg>
);

export default SvgChevronLeft;
