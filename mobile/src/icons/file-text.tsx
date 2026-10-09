import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgFileText = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M9 1.5H4.5C3.67157 1.5 3 2.17157 3 3V13C3 13.8284 3.67157 14.5 4.5 14.5H11.5C12.3284 14.5 13 13.8284 13 13V5.5L9 1.5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <Path
      d="M8.5 1.5V5C8.5 5.55228 8.94772 6 9.5 6H13"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <Path
      d="M5.5 8.5H10.5M5.5 11H8.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgFileText;
