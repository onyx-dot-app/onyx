import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web copy icon.
// The web source wraps the path in a <clipPath> bounding to the 16x16 box; that
// clip is a no-op for rendering and is dropped here.
/** Copy / duplicate (overlapping sheets). */
function SvgCopy(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M3.33333 9.99999H2.66666C2.31304 9.99999 1.9739 9.85952 1.72385 9.60947C1.4738 9.35942 1.33333 9.02028 1.33333 8.66666V2.66666C1.33333 2.31304 1.4738 1.9739 1.72385 1.72385C1.9739 1.4738 2.31304 1.33333 2.66666 1.33333H8.66666C9.02028 1.33333 9.35942 1.4738 9.60947 1.72385C9.85952 1.9739 9.99999 2.31304 9.99999 2.66666V3.33333M7.33333 5.99999H13.3333C14.0697 5.99999 14.6667 6.59695 14.6667 7.33333V13.3333C14.6667 14.0697 14.0697 14.6667 13.3333 14.6667H7.33333C6.59695 14.6667 5.99999 14.0697 5.99999 13.3333V7.33333C5.99999 6.59695 6.59695 5.99999 7.33333 5.99999Z"
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

export { SvgCopy };
