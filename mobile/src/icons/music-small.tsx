import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgMusicSmall = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M9.5 10V5L10.5 4.75M9.5 10C9.5 10.8284 8.82843 11.5 8 11.5C7.17157 11.5 6.5 10.8284 6.5 10C6.5 9.17157 7.17157 8.5 8 8.5C8.82843 8.5 9.5 9.17157 9.5 10Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgMusicSmall;
