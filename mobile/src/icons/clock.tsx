import Svg, { ClipPath, Defs, G, Path, Rect } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgClock = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <G clipPath="url(#clock-clip)">
      <Path
        d="M7.99999 3.99999V7.99999L10.6667 9.33333M14.6667 7.99999C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 7.99999C1.33333 4.3181 4.3181 1.33333 7.99999 1.33333C11.6819 1.33333 14.6667 4.3181 14.6667 7.99999Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </G>
    <Defs>
      <ClipPath id="clock-clip">
        <Rect width={16} height={16} fill="white" />
      </ClipPath>
    </Defs>
  </Svg>
);

export default SvgClock;
