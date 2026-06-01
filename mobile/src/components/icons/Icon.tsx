import { Svg, type SvgProps } from "react-native-svg";

import { useThemeColors } from "@/theme/ThemeProvider";
import type { ColorToken } from "@/theme/generated/colors";

// Onyx rule: ONLY curated icons hand-ported from the web Opal set — no icon-font
// libraries (lucide, fa, …). To port a new icon:
//   1. Find the source: web/lib/opal/src/icons/<name>.tsx (a `<svg>` with a
//      `viewBox` and `<path d=...>`). Note the viewBox and whether it's
//      STROKE-based (Opal default; color drives `stroke`, `fill="none"`) or
//      FILL-based (color drives `fill`).
//   2. Build a component on the `<Icon>` wrapper below so size + color stay
//      consistent. Web uses CSS `currentColor`; RN has none, so the resolved
//      color MUST be passed explicitly into `stroke`/`fill` — `<Icon>` resolves
//      the token and hands it to children via the render-prop (see SvgX.tsx).
//   3. Register the component in `index.ts`.

export type IconVariant = "stroke" | "fill";

export interface IconProps {
  size?: number;
  // ColorToken (resolved for the active scheme) or a raw color string. Defaults
  // to the current text color (text-05), matching surrounding <Text>.
  color?: ColorToken | string;
  style?: SvgProps["style"];
}

export interface IconRenderProps {
  color: string;
}

interface IconRootProps extends IconProps {
  viewBox: string;
  children: (props: IconRenderProps) => React.ReactNode;
}

function isColorToken(value: string, colors: Record<string, string>): boolean {
  return Object.prototype.hasOwnProperty.call(colors, value);
}

function Icon({
  size = 20,
  color = "text-05",
  style,
  viewBox,
  children,
}: IconRootProps) {
  const colors = useThemeColors();

  // A bare token like "text-05" resolves against the active scheme; anything
  // else (hex/rgba/named) is a literal color. Resolved here, never via dynamic
  // className strings — NativeWind can't see those.
  const resolved =
    typeof color === "string" && isColorToken(color, colors)
      ? colors[color as ColorToken]
      : color;

  return (
    <Svg width={size} height={size} viewBox={viewBox} fill="none" style={style}>
      {children({ color: resolved })}
    </Svg>
  );
}

export { Icon };
