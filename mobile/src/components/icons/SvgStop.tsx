import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web stop icon. Web fills the square with a tint and strokes
// currentColor; here we render it solid in the icon color (fill + stroke both
// `color`) for the filled primary button.
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
