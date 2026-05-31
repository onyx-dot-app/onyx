import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/expand.tsx (stroke-based, viewBox 16).
/** Chevrons pointing up and down / expand. */
function SvgExpand(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M4.99994 5.49995L7.52858 2.97131C7.78891 2.71098 8.21105 2.71098 8.47138 2.97131L11 5.49995M5.00024 10.5L7.5288 13.0286C7.78914 13.2889 8.21127 13.2889 8.4716 13.0286L11.0002 10.5"
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

export { SvgExpand };
