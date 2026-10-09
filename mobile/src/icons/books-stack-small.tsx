import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgBooksStackSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M6 10.5H10.5M5 8H9.5M6.5 5.5H11"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgBooksStackSmall;
