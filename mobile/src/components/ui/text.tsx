// Text — the React Native port of web's Opal `Text`
// (web/lib/opal/src/components/text/components.tsx). Mirrors it 1:1:
//   • `font` selects a typography preset by the SAME names as web ("main-ui-body",
//     "heading-h3", …). Each maps to a `font-*` NativeWind utility (FONT_CONFIG),
//     exactly like web's FONT_CONFIG maps to the `@utility font-*` classes — so the
//     `font-` prefixed token name now exists on mobile too. The utilities are
//     generated from the shared tokens (@onyx-ai/shared/nativewind-typography,
//     registered in tailwind.config.js) and carry family + size + weight +
//     line-height + letter-spacing, so we never hand-pick `font-semibold`/`text-base`.
//   • `color` is a typed token (COLOR_CONFIG), default "text-04". `inherit` renders
//     no color class (RN Text inherits its parent's color when nested).
// TextFont + TextColor are the single canonical unions, shared with web Opal from
// the neutral @onyx-ai/shared/contracts.
//
// Differences from web (no RN equivalent, intentionally omitted): the `as` tag prop
// and inline-markdown `RichStr` children (web's `resolveStr`). `maxLines` maps to RN
// `numberOfLines` + a tail ellipsis; `nowrap` clips one line with NO ellipsis (web's
// `nowrap` overflows without one — RN can't overflow-visible, so clip is the closest).
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
  // Web parity: `maxLines` truncates with a tail ellipsis; `nowrap` clips one line
  // with no ellipsis. Non-positive `maxLines` is "no limit" (web treats it as falsy).
  // A caller's own `numberOfLines` is honored when neither prop is set.
  const clampLines =
    maxLines != null && maxLines > 0 ? maxLines : nowrap ? 1 : numberOfLines;
  const ellipsizeMode =
    maxLines != null && maxLines > 0 ? "tail" : nowrap ? "clip" : undefined;
  return (
    <RNText
      numberOfLines={clampLines}
      ellipsizeMode={ellipsizeMode}
      // `px-2` = 2px here: mobile's NativeWind theme uses a pixel-valued spacing
      // scale (@onyx-ai/shared), so `2` is 2px (NOT web Tailwind's 8px) — this
      // matches web Opal Text's `px-[2px]`, using the on-scale token over `[2px]`.
      className={cn("px-2", FONT_CONFIG[font], COLOR_CONFIG[color], className)}
      {...props}
    />
  );
}

export { Text, type TextProps, type TextFont, type TextColor };
