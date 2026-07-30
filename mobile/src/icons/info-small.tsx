import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgInfoSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M8 11V7H7M8 11H7M8 11H9M8 4.7V4.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgInfoSmall;
