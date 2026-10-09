import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgCpu = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M6.09091 1V2.90909M9.90909 1V2.90909M6.09091 13.0909V15M9.90909 13.0909V15M13.0909 6.09091H15M13.0909 9.27273H15M1 6.09091H2.90909M1 9.27273H2.90909M4.18182 2.90909H11.8182C12.5211 2.90909 13.0909 3.47891 13.0909 4.18182V11.8182C13.0909 12.5211 12.5211 13.0909 11.8182 13.0909H4.18182C3.47891 13.0909 2.90909 12.5211 2.90909 11.8182V4.18182C2.90909 3.47891 3.47891 2.90909 4.18182 2.90909ZM6 6H10V10H6V6Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgCpu;
