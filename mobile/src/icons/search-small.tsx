import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgSearchSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M9.69454 9.69454C10.7685 8.6206 10.7685 6.8794 9.69454 5.80546C8.6206 4.73151 6.8794 4.73151 5.80546 5.80546C4.73151 6.8794 4.73151 8.6206 5.80546 9.69454C6.8794 10.7685 8.6206 10.7685 9.69454 9.69454ZM9.69454 9.69454L11 11"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgSearchSmall;
