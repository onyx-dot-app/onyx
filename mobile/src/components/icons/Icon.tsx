import { Svg, type SvgProps } from "react-native-svg";

import { useThemeColors } from "@/theme/ThemeProvider";
import type { ColorToken } from "@/theme/generated/colors";

// ===========================================================================
// Icon system — porting Opal/curated SVGs to React Native
// ===========================================================================
//
// Onyx rule: ONLY curated icons. No icon-font libraries (lucide, fa, …). Each
// icon is hand-ported from the web Opal set so we keep full control over the
// path data, stroke semantics, and licensing.
//
// HOW TO PORT A NEW ICON (web SVG -> RN component):
//   1. Find the source in the web repo. Curated Opal icons live in
//        web/lib/opal/src/icons/<name>.tsx
//      Each is a React `<svg>` with a `viewBox` and one or more `<path d=...>`.
//   2. Note the `viewBox` (often "0 0 16 16", but some are 28/32) and whether
//      the icon is STROKE-based or FILL-based:
//        - Opal curated icons are STROKE-based: the web `<svg>` sets
//          `stroke="currentColor"` + `fill="none"`, and each `<path>` carries
//          a `strokeWidth` / `strokeLinecap` / `strokeLinejoin`. The COLOR
//          drives `stroke`, NOT `fill`.
//        - A few icons are FILL-based: the `<path>` is filled with
//          `currentColor`. There the COLOR drives `fill`.
//   3. Create a component in this directory using `react-native-svg`:
//        <Svg viewBox={...} width={size} height={size}>
//          <Path d="..." stroke={color} strokeWidth={...} fill="none" ... />
//        </Svg>
//      Build it on top of the `<Icon>` wrapper below so size + color
//      resolution stay consistent. Pass `variant="fill"` for fill-based icons.
//   4. Web uses CSS `currentColor`; RN has no `currentColor`, so the resolved
//      color MUST be passed explicitly into `stroke`/`fill`. `<Icon>` resolves
//      the `color` token (or raw string) for you and exposes it to children
//      via the render-prop — see SvgX.tsx etc. for the pattern.
//   5. Register the new component in `index.ts`.
//
// NATIVEWIND NOTE: colors here are resolved to concrete values (hex/rgba) and
// passed via the `stroke`/`fill` props — never via dynamic className strings.
// ===========================================================================

/**
 * Whether an icon's color drives the SVG `stroke` (Opal default, line icons)
 * or the `fill` (solid/glyph icons).
 */
export type IconVariant = "stroke" | "fill";

export interface IconProps {
  /** Square edge length in px. Default: 20. */
  size?: number;

  /**
   * Icon color. Either a design-system `ColorToken` (resolved for the active
   * scheme) or a raw color string (e.g. "#fff", "rgba(...)"). Defaults to the
   * current text color (`text-05`), matching surrounding `<Text>`.
   */
  color?: ColorToken | string;

  /** Standard RN style passthrough on the root `<Svg>`. */
  style?: SvgProps["style"];
}

/** Props passed to the render-prop children of `<Icon>`. */
export interface IconRenderProps {
  /** Resolved color string to apply to `stroke` or `fill`. */
  color: string;
}

interface IconRootProps extends IconProps {
  /** SVG coordinate system of the source artwork, e.g. "0 0 16 16". */
  viewBox: string;
  /**
   * Render the `<Path>`/glyph children. Receives the resolved color so each
   * icon decides whether it lands on `stroke` (line) or `fill` (solid).
   */
  children: (props: IconRenderProps) => React.ReactNode;
}

/** Token key set, used to discriminate `ColorToken` from a raw color string. */
function isColorToken(value: string, colors: Record<string, string>): boolean {
  return Object.prototype.hasOwnProperty.call(colors, value);
}

/**
 * Base wrapper that standardizes size + color resolution for every ported
 * icon. Resolves a `ColorToken` to a concrete value (or passes a raw color
 * through) and renders a square `<Svg>` with the given `viewBox`.
 *
 * Individual icons compose this and supply their `<Path>` data:
 *   <Icon viewBox="0 0 16 16" {...props}>
 *     {({ color }) => <Path d="…" stroke={color} fill="none" strokeWidth={1.5} />}
 *   </Icon>
 */
function Icon({
  size = 20,
  color = "text-05",
  style,
  viewBox,
  children,
}: IconRootProps) {
  const colors = useThemeColors();

  // A bare token like "text-05" resolves against the active scheme; anything
  // else (hex / rgba / named) is treated as a literal color.
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
