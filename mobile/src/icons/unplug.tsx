import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgUnplug = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M1 1L5.0778 5.0778M15 15L12 12M15 10.5H14M12 12.5H8.5C6.01472 12.5 4 10.4853 4 8M12 12.5V14M12 12.5V12M12 3.5H8.5C8.04537 3.5 7.60649 3.56742 7.1928 3.6928M12 3.5V5.5M12 3.5V2M12 5.5H15M12 5.5V8.5M4 8H1M4 8C4 6.88463 4.40579 5.86403 5.0778 5.0778M5.0778 5.0778L12 12"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgUnplug;
