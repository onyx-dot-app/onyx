import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web upload-square icon.
function SvgUploadSquare(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M11 14H12.6667C13.3929 14 14 13.3929 14 12.6667V3.33333C14 2.60711 13.3929 2 12.6667 2H3.33333C2.60711 2 2 2.60711 2 3.33333V12.6667C2 13.3929 2.60711 14 3.33333 14H5M10.6666 8.16667L7.99998 5.5M7.99998 5.5L5.33331 8.16667M7.99998 5.5V14"
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

export { SvgUploadSquare };
