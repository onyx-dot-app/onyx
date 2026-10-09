import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgExpand = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M4.99994 5.49995L7.52858 2.97131C7.78891 2.71098 8.21105 2.71098 8.47138 2.97131L11 5.49995M5.00024 10.5L7.5288 13.0286C7.78914 13.2889 8.21127 13.2889 8.4716 13.0286L11.0002 10.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgExpand;
