import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgArrowRightCircle = ({ size = 16, ...props }: IconProps) => (
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
      d="M7.99999 10.6667L10.6667 8.00001M10.6667 8.00001L7.99999 5.33334M10.6667 8.00001L5.33333 8.00001M14.6667 8.00001C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 8.00001C1.33333 4.31811 4.3181 1.33334 7.99999 1.33334C11.6819 1.33334 14.6667 4.31811 14.6667 8.00001Z"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgArrowRightCircle;
