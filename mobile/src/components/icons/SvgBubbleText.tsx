import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web bubble-text icon.
/** Chat bubble with text lines — a chat session row glyph. */
function SvgBubbleText(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M10.4939 6.5H5.5M8.00607 9.5H5.50607M1.5 13.5H10.5C12.7091 13.5 14.5 11.7091 14.5 9.5V6.5C14.5 4.29086 12.7091 2.5 10.5 2.5H5.5C3.29086 2.5 1.5 4.29086 1.5 6.5V13.5Z"
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

export { SvgBubbleText };
