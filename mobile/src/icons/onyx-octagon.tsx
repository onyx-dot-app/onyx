import Svg, { ClipPath, Defs, G, Path, Rect } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgOnyxOctagon = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <G clipPath="url(#clip0_586_578)">
      <Path
        d="M4.5 2.50002L8 1.00002L11.5 2.50002M13.5 4.50002L15 8.00001L13.5 11.5M11.5 13.5L8 15L4.5 13.5M2.5 11.5L1 8L2.5 4.50002"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </G>
    <Defs>
      <ClipPath id="clip0_586_578">
        <Rect width={16} height={16} fill="white" />
      </ClipPath>
    </Defs>
  </Svg>
);

export default SvgOnyxOctagon;
