// React Native port of web's Opal `Text` (web/lib/opal/src/components/text/components.tsx),
// mirrored 1:1: `font` → a `font-*` NativeWind utility (FONT_CONFIG, generated from the
// shared tokens); `color` → a token class (COLOR_CONFIG; default "text-04", "inherit" →
// no class). TextFont/TextColor are the shared canonical unions from
// @onyx-ai/shared/contracts (not the RN-only /native).
//
// Omitted vs web (no RN equivalent): the `as` tag and inline-markdown children.
// `maxLines` → numberOfLines + tail ellipsis; `nowrap` clips one line without one.
import type { TextColor, TextFont } from "@onyx-ai/shared/contracts";
import * as React from "react";
import { Text as RNText } from "react-native";

import { cn } from "@/lib/utils";

// font preset name -> `font-*` utility class (= web's FONT_CONFIG). Literal strings
// so NativeWind's class scanner picks them up.
const FONT_CONFIG: Record<TextFont, string> = {
  "heading-h1": "font-heading-h1",
  "heading-h2": "font-heading-h2",
  "heading-h3": "font-heading-h3",
  "heading-h3-muted": "font-heading-h3-muted",
  "main-content-body": "font-main-content-body",
  "main-content-muted": "font-main-content-muted",
  "main-content-emphasis": "font-main-content-emphasis",
  "main-content-mono": "font-main-content-mono",
  "main-ui-body": "font-main-ui-body",
  "main-ui-muted": "font-main-ui-muted",
  "main-ui-action": "font-main-ui-action",
  "main-ui-mono": "font-main-ui-mono",
  "secondary-body": "font-secondary-body",
  "secondary-action": "font-secondary-action",
  "secondary-mono": "font-secondary-mono",
  "secondary-mono-label": "font-secondary-mono-label",
  "figure-small-label": "font-figure-small-label",
  "figure-small-value": "font-figure-small-value",
  "figure-keystroke": "font-figure-keystroke",
};

// color token -> text color class (= web's COLOR_CONFIG). `inherit` -> no class.
const COLOR_CONFIG: Record<TextColor, string | null> = {
  inherit: null,
  "text-01": "text-text-01",
  "text-02": "text-text-02",
  "text-03": "text-text-03",
  "text-04": "text-text-04",
  "text-05": "text-text-05",
  "text-inverted-01": "text-text-inverted-01",
  "text-inverted-02": "text-text-inverted-02",
  "text-inverted-03": "text-text-inverted-03",
  "text-inverted-04": "text-text-inverted-04",
  "text-inverted-05": "text-text-inverted-05",
  "text-light-03": "text-text-light-03",
  "text-light-05": "text-text-light-05",
  "text-dark-03": "text-text-dark-03",
  "text-dark-05": "text-text-dark-05",
  "status-error-01": "text-status-error-01",
  "status-error-02": "text-status-error-02",
  "status-error-05": "text-status-error-05",
  "status-success-01": "text-status-success-01",
  "status-success-02": "text-status-success-02",
  "status-success-05": "text-status-success-05",
};

interface TextProps extends React.ComponentProps<typeof RNText> {
  /** Typography preset (same names as web's Opal Text). @default "main-ui-body" */
  font?: TextFont;
  /** Color token. @default "text-04" */
  color?: TextColor;
  /** Keep text on one line, clipped without an ellipsis (web's `nowrap`). */
  nowrap?: boolean;
  /** Truncate to N lines with a tail ellipsis (web's `maxLines`). */
  maxLines?: number;
}

function Text({
  className,
  font = "main-ui-body",
  color = "text-04",
  nowrap,
  maxLines,
  numberOfLines,
  ...props
}: TextProps) {
  // maxLines<=0 means "no limit" (web treats it as falsy); fall back to the caller's
  // own numberOfLines when neither maxLines nor nowrap is set.
  const clamped = maxLines != null && maxLines > 0;
  const clampLines = clamped ? maxLines : nowrap ? 1 : numberOfLines;
  const ellipsizeMode = clamped ? "tail" : nowrap ? "clip" : undefined;
  return (
    <RNText
      numberOfLines={clampLines}
      ellipsizeMode={ellipsizeMode}
      // `px-2` = 2px: mobile's spacing scale is pixel-valued, not web Tailwind's 8px.
      // Matches web Opal Text's `px-[2px]` — on-scale token, not `[2px]`.
      className={cn("px-2", FONT_CONFIG[font], COLOR_CONFIG[color], className)}
      {...props}
    />
  );
}

export { Text, type TextProps, type TextFont, type TextColor };
