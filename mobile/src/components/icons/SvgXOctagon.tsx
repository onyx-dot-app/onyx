import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/x-octagon.tsx (stroke-based, viewBox 15).
/** X inside an octagon. */
function SvgXOctagon(props: IconProps) {
  return (
    <Icon viewBox="0 0 15 15" {...props}>
      {({ color }) => (
        <Path
          d="M9.41667 5.41667L5.41667 9.41667M5.41667 5.41667L9.41667 9.41667M4.65667 0.75H10.1767L14.0833 4.65667V10.1767L10.1767 14.0833H4.65667L0.75 10.1767V4.65667L4.65667 0.75Z"
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

export { SvgXOctagon };
