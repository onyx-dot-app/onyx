import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/download.tsx (stroke-based, viewBox 16).
/** Download / save to device. */
function SvgDownload(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M14 10V12.6667C14 13.3929 13.3929 14 12.6667 14H3.33333C2.60711 14 2 13.3929 2 12.6667V10M4.66667 6.66667L8 10M8 10L11.3333 6.66667M8 10L8 2"
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

export { SvgDownload };
