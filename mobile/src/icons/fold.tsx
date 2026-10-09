import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgFold = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M11 3.25L8.47136 5.77857C8.21103 6.0389 7.78889 6.0389 7.52856 5.77857L4.99999 3.25M11 12.75L8.47136 10.2214C8.21103 9.96103 7.78889 9.96103 7.52856 10.2214L4.99999 12.75"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgFold;
