import {
  Text as RNText,
  type TextProps as RNTextProps,
  type TextStyle,
} from "react-native";

import { typography, type TypographyPreset } from "@/theme/generated/typography";
import { useThemeColors } from "@/theme/ThemeProvider";
import type { ColorToken } from "@/theme/generated/colors";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Font preset — one of the 19 Opal typography presets (doc-03 token system). */
export type TextFont = TypographyPreset;

/**
 * Color variant — any color token from the doc-03 palette. This is a superset
 * of the web Opal `TextColor` union (which only allows `text-0X` / inverted /
 * light / dark variants) so callers can use semantic tokens directly on RN.
 */
export type TextColor = ColorToken;

interface TextProps extends Omit<RNTextProps, "style"> {
  /** Font preset. Default: `"main-ui-body"`. */
  font?: TextFont;

  /** Color token. Default: `"text-05"`. */
  color?: TextColor;

  /** Standard RN style override, merged after the resolved typography/color. */
  style?: RNTextProps["style"];

  children?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

/**
 * Native mirror of the Opal `Text` component.
 *
 * NativeWind compiles classes by scanning source for STATIC strings, so a
 * dynamic className like `text-${color}` would silently produce no style.
 * Therefore typography and color are applied through the `style` prop — never
 * through dynamically-built classNames:
 *   - typography via `typography[font]` (a style object from doc-03)
 *   - color via `useThemeColors()[color]` (resolved hex for the active scheme)
 *
 * TODO: port the web-only `as` (HTML tag) and inline-markdown (`RichStr`) APIs
 * once the markdown renderer lands.
 */
function Text({
  font = "main-ui-body",
  color = "text-05",
  style,
  children,
  ...rest
}: TextProps) {
  const colors = useThemeColors();

  // The generated typography presets use design-token font weights (e.g. "450")
  // that fall outside RN's strict `fontWeight` literal union, so cast to
  // `TextStyle`. RN renders these fine at runtime (rounding to the nearest
  // supported weight on platforms that need it).
  const preset = typography[font] as TextStyle;

  return (
    <RNText {...rest} style={[preset, { color: colors[color] }, style]}>
      {children}
    </RNText>
  );
}

export { Text, type TextProps };
