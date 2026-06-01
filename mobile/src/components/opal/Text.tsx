import {
  Text as RNText,
  type TextProps as RNTextProps,
  type TextStyle,
} from "react-native";

import { typography, type TypographyPreset } from "@/theme/generated/typography";
import { useThemeColors } from "@/theme/ThemeProvider";
import type { ColorToken } from "@/theme/generated/colors";

export type TextFont = TypographyPreset;

// Superset of web Opal TextColor (which only allows text-0X / inverted / light / dark)
// so callers can use semantic tokens directly on RN.
export type TextColor = ColorToken;

interface TextProps extends Omit<RNTextProps, "style"> {
  font?: TextFont;
  color?: TextColor;
  style?: RNTextProps["style"];
  children?: React.ReactNode;
}

// Native mirror of web Opal Text. NativeWind only scans STATIC class strings, so a dynamic
// `text-${color}` would silently produce no style — typography and color go through `style` instead.
// TODO: port the web-only `as` (HTML tag) and inline-markdown (`RichStr`) APIs once the markdown renderer lands.
function Text({
  font = "main-ui-body",
  color = "text-05",
  style,
  children,
  ...rest
}: TextProps) {
  const colors = useThemeColors();

  // Generated presets use token font weights (e.g. "450") outside RN's fontWeight literal union;
  // cast to TextStyle — RN renders them fine, rounding to the nearest supported weight where needed.
  const preset = typography[font] as TextStyle;

  return (
    <RNText {...rest} style={[preset, { color: colors[color] }, style]}>
      {children}
    </RNText>
  );
}

export { Text, type TextProps };
