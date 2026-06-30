import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgStop = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    {...props}
  >
    <Path d="M12 4H4V12H12V4Z" strokeLinecap="round" strokeLinejoin="round" />
  </Svg>
);

export default SvgStop;
