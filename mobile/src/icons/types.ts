import type * as React from "react";
import type { SvgProps } from "react-native-svg";

// React Native counterpart of web Opal's icon types (web/lib/opal/src/types.ts).
// Same shape, retargeted to react-native-svg. Icons render with
// `stroke="currentColor"`, so color flows from the `color` prop — the `Icon`
// wrapper (components/ui/icon.tsx) sets it from a `text-*` token class.
export interface IconProps extends SvgProps {
  className?: string;
  size?: number;
  title?: string;
}

export type IconFunctionComponent = React.FunctionComponent<IconProps>;
