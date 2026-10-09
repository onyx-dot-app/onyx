import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgBooksLineSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M8.25 5.5V10M10.75 5.5V10M5.91469 5.65333L4.75 10"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgBooksLineSmall;
