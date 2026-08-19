import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgArrowUp = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    {...props}
  >
    <Path
      d="M8 2.6665V13.3335M8 2.6665L4 6.6665M8 2.6665L12 6.6665"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgArrowUp;
