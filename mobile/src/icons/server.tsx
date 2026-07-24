import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgServer = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M4 4H4.00666M4 12H4.00666M2.66666 1.33334H13.3333C14.0697 1.33334 14.6667 1.9303 14.6667 2.66668V5.33334C14.6667 6.06972 14.0697 6.66668 13.3333 6.66668H2.66666C1.93028 6.66668 1.33333 6.06972 1.33333 5.33334V2.66668C1.33333 1.9303 1.93028 1.33334 2.66666 1.33334ZM2.66666 9.33334H13.3333C14.0697 9.33334 14.6667 9.9303 14.6667 10.6667V13.3333C14.6667 14.0697 14.0697 14.6667 13.3333 14.6667H2.66666C1.93028 14.6667 1.33333 14.0697 1.33333 13.3333V10.6667C1.33333 9.9303 1.93028 9.33334 2.66666 9.33334Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgServer;
