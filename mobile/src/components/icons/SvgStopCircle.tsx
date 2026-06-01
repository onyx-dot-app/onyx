import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web stop-circle icon.
function SvgStopCircle(props: IconProps) {
  return (
    <Icon viewBox="0 0 15 15" {...props}>
      {({ color }) => (
        <>
          <Path
            d="M7.41667 14.0833C11.0986 14.0833 14.0833 11.0986 14.0833 7.41667C14.0833 3.73477 11.0986 0.75 7.41667 0.75C3.73477 0.75 0.75 3.73477 0.75 7.41667C0.75 11.0986 3.73477 14.0833 7.41667 14.0833Z"
            stroke={color}
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
          <Path
            d="M9.41667 5.41667H5.41667V9.41667H9.41667V5.41667Z"
            stroke={color}
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </>
      )}
    </Icon>
  );
}

export { SvgStopCircle };
