import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web log-out icon.
function SvgLogOut(props: IconProps) {
  return (
    <Icon viewBox="0 0 24 24" {...props}>
      {({ color }) => (
        <>
          <Path
            d="M9 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H9"
            stroke={color}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
          <Path
            d="M16 17L21 12L16 7"
            stroke={color}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
          <Path
            d="M21 12H9"
            stroke={color}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </>
      )}
    </Icon>
  );
}

export { SvgLogOut };
