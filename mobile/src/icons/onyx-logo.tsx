import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

// Paths fill with `currentColor` (RN can't read a CSS var), tinted via the `Icon` color class.
const SvgOnyxLogo = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 64 64"
    fill="currentColor"
    {...props}
  >
    <Path d="M10.4014 13.25L18.875 32L10.3852 50.75L2 32L10.4014 13.25Z" />
    <Path d="M53.5264 13.25L62 32L53.5102 50.75L45.125 32L53.5264 13.25Z" />
    <Path d="M32 45.125L50.75 53.5625L32 62L13.25 53.5625L32 45.125Z" />
    <Path d="M32 2L50.75 10.4375L32 18.875L13.25 10.4375L32 2Z" />
  </Svg>
);

export default SvgOnyxLogo;
