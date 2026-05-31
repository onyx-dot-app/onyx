import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/x-circle.tsx (stroke-based, viewBox 15).
/** X inside a circle / close in a circle. */
function SvgXCircle(props: IconProps) {
  return (
    <Icon viewBox="0 0 15 15" {...props}>
      {({ color }) => (
        <Path
          d="M9.41667 5.41667L5.41667 9.41667M5.41667 5.41667L9.41667 9.41667M14.0833 7.41667C14.0833 11.0986 11.0986 14.0833 7.41667 14.0833C3.73477 14.0833 0.75 11.0986 0.75 7.41667C0.75 3.73477 3.73477 0.75 7.41667 0.75C11.0986 0.75 14.0833 3.73477 14.0833 7.41667Z"
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

export { SvgXCircle };
