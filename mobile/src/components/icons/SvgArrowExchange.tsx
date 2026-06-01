import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Mirrors web arrow-exchange icon.
function SvgArrowExchange(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M5.22381 2.5L3.19527 4.52854C3.06509 4.65871 3 4.82932 3 4.99994M5.22392 7.5L3.19526 5.47134C3.06509 5.34117 3 5.17056 3 4.99994M13 4.99994H3M10.7761 8.50003L12.8047 10.5286C12.9349 10.6587 13 10.8294 13 11M10.7761 13.5L12.8047 11.4714C12.9349 11.3412 13 11.1706 13 11M3 11H13"
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

export { SvgArrowExchange };
