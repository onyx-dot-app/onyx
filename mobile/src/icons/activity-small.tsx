import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgActivitySmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M11.5 8H10L9 11L7 5L6 8H4.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgActivitySmall;
