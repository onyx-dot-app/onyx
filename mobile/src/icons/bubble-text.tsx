import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgBubbleText = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M10.4939 6.5H5.5M8.00607 9.5H5.50607M1.5 13.5H10.5C12.7091 13.5 14.5 11.7091 14.5 9.5V6.5C14.5 4.29086 12.7091 2.5 10.5 2.5H5.5C3.29086 2.5 1.5 4.29086 1.5 6.5V13.5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgBubbleText;
