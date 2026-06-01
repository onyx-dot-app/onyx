import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web arrow-up icon. No curated "send" glyph exists, so this doubles as
// the composer's send affordance (exported as the SvgSend alias in index.ts).
function SvgArrowUp(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M8 2.6665V13.3335M8 2.6665L4 6.6665M8 2.6665L12 6.6665"
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

export { SvgArrowUp };
