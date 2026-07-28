import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgTerminalSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M5.5 10L7.5 8L5.5 6M8.5 10.5H10.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgTerminalSmall;
