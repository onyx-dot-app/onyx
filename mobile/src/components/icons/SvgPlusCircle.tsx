import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web plus-circle icon.
// The web source wraps the path in a decorative clipPath; it's unnecessary here
// since the artwork fits the viewBox.
/** Plus in a circle — "Add Files". */
function SvgPlusCircle(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M7.99999 5.33333V10.6667M5.33333 7.99999H10.6667M14.6667 7.99999C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 7.99999C1.33333 4.3181 4.3181 1.33333 7.99999 1.33333C11.6819 1.33333 14.6667 4.3181 14.6667 7.99999Z"
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

export { SvgPlusCircle };
