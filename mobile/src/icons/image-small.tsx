import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgImageSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M9.5 11.5L6.20711 8.20711C5.81658 7.81658 5.18342 7.81658 4.79289 8.20711L4 9M9.75 7.5C10.4404 7.5 11 6.94037 11 6.25C11 5.55964 10.4404 5 9.75 5C9.05963 5 8.5 5.55964 8.5 6.25C8.5 6.94037 9.05963 7.5 9.75 7.5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgImageSmall;
