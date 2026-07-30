import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

// clipPath bounded to the full 16x16 viewBox is a visual no-op, so it's omitted.
const SvgSliders = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M2.66666 14V9.33333M2.66666 6.66667V2M7.99999 14V8M7.99999 5.33333V2M13.3333 14V10.6667M13.3333 8V2M0.666656 9.33333H4.66666M5.99999 5.33333H9.99999M11.3333 10.6667H15.3333"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgSliders;
