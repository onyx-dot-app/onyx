import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web add-lines icon.
/** Lines with a plus — "Set Instructions". */
function SvgAddLines(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M14 6H2M14 3H2M6 12H2M11.5 9.5V12M11.5 12V14.5M11.5 12H9M11.5 12H14M8.5 9H2"
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

export { SvgAddLines };
