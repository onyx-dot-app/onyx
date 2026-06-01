import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/stop.tsx (viewBox 16). Web fills the square
// with --background-tint-00 and strokes currentColor; on a filled primary button
// we render a solid rounded square in the icon color (fill + stroke both `color`).
/** Stop square (send button while streaming). */
function SvgStop(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M12 4H4V12H12V4Z"
          fill={color}
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </Icon>
  );
}

export { SvgStop };
