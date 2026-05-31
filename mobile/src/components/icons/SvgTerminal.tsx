import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/terminal.tsx (stroke-based, viewBox 16).
/** Terminal / command prompt. */
function SvgTerminal(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M2.66667 11.3333L6.66667 7.33331L2.66667 3.33331M8.00001 12.6666H13.3333"
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

export { SvgTerminal };
