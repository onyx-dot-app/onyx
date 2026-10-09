import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgHourglass = ({ size = 16, ...props }: IconProps) => (
  <Svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <Path
      d="M8 8L4.44793 5.72667C4.06499 5.48159 3.83333 5.05828 3.83333 4.60364V1.83333H12.1667V4.60364C12.1667 5.05828 11.935 5.48159 11.5521 5.72667L8 8ZM8 8L11.5521 10.2733C11.935 10.5184 12.1667 10.9417 12.1667 11.3963V14.1667H3.83333V11.3963C3.83333 10.9417 4.06499 10.5184 4.44793 10.2733L8 8ZM13.5 14.1667H2.5M13.5 1.83333H2.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default SvgHourglass;
