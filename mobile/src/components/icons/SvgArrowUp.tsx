import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/arrow-up.tsx (stroke-based, viewBox 16).
// The Opal curated set has no dedicated "send" glyph; arrow-up is the canonical
// send affordance in the composer, so `SvgSend` is exported as an alias below.
/** Upward arrow (also used as the chat "send" affordance). */
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
