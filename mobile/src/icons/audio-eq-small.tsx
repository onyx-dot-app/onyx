import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgAudioEqSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M5 9V7M7 11V5M9 9.5V6.5M11 9V7"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgAudioEqSmall;
