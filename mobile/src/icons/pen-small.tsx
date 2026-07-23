import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgPenSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M6.5 11L11.5 6L10 4.5L5 9.5L5 11H6.5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgPenSmall;
