import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgProductboard = ({ size = 16, ...props }: IconProps) => (
  <Svg width={size} height={size} viewBox="0 0 52 52" fill="none" {...props}>
    <Path
      d="M19.9991 25.9997L35.9983 41.7494H4L19.9991 25.9997Z"
      fill="#FF2638"
    />
    <Path d="M4 10.25L19.9991 25.9997L35.9983 10.25H4Z" fill="#FFC600" />
    <Path
      d="M19.9991 25.9997L35.9983 41.7494L52 25.9997L35.9983 10.25L19.9991 25.9997Z"
      fill="#0079F2"
    />
  </Svg>
);
export default SvgProductboard;
