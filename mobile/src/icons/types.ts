import type * as React from "react";
import type { SvgProps } from "react-native-svg";

// Icons render with `stroke="currentColor"`; color flows from the `color` prop,
// which the `Icon` wrapper sets from a `text-*` token class.
export interface IconProps extends SvgProps {
  className?: string;
  size?: number;
  title?: string;
}

export type IconFunctionComponent = React.FunctionComponent<IconProps>;
