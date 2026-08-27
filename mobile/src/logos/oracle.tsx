import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgOracle = ({ size = 16, ...props }: IconProps) => (
  <Svg width={size} height={size} viewBox="0 0 32 21" {...props}>
    <Path
      fill="#C74634"
      d="M9.9,20.1c-5.5,0-9.9-4.4-9.9-9.9c0-5.5,4.4-9.9,9.9-9.9h11.6c5.5,0,9.9,4.4,9.9,9.9c0,5.5-4.4,9.9-9.9,9.9H9.9 M21.2,16.6c3.6,0,6.4-2.9,6.4-6.4c0-3.6-2.9-6.4-6.4-6.4h-11c-3.6,0-6.4,2.9-6.4,6.4s2.9,6.4,6.4,6.4H21.2"
    />
  </Svg>
);
export default SvgOracle;
