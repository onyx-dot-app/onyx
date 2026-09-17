import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgMail = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M14.6667 3.99996C14.6667 3.26663 14.0667 2.66663 13.3333 2.66663H2.66668C1.93334 2.66663 1.33334 3.26663 1.33334 3.99996M14.6667 3.99996V12C14.6667 12.7333 14.0667 13.3333 13.3333 13.3333H2.66668C1.93334 13.3333 1.33334 12.7333 1.33334 12V3.99996M14.6667 3.99996L8.00001 8.66663L1.33334 3.99996"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgMail;
