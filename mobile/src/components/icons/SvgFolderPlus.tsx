import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web folder-plus icon.
function SvgFolderPlus(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M7.99999 7.33333V11.3333M5.99999 9.33333H10M14.6667 12.6667C14.6667 13.0203 14.5262 13.3594 14.2761 13.6095C14.0261 13.8595 13.6869 14 13.3333 14H2.66666C2.31304 14 1.9739 13.8595 1.72385 13.6095C1.4738 13.3594 1.33333 13.0203 1.33333 12.6667V3.33333C1.33333 2.97971 1.4738 2.64057 1.72385 2.39052C1.9739 2.14048 2.31304 2 2.66666 2H5.99999L7.33333 4H13.3333C13.6869 4 14.0261 4.14048 14.2761 4.39052C14.5262 4.64057 14.6667 4.97971 14.6667 5.33333V12.6667Z"
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

export { SvgFolderPlus };
