import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web fold icon.
function SvgFold(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M11 3.25L8.47136 5.77857C8.21103 6.0389 7.78889 6.0389 7.52856 5.77857L4.99999 3.25M11 12.75L8.47136 10.2214C8.21103 9.96103 7.78889 9.96103 7.52856 10.2214L4.99999 12.75"
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      )}
    </Icon>
  );
}

export { SvgFold };
