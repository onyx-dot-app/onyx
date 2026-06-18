// Text — the React Native counterpart of web's Opal `Text`. Typography comes from
// the shared design-system presets (`@onyx-ai/shared` `textPresets`), selected by a
// `font` prop with the exact same names as web (`TextFont`): "main-ui-body",
// "secondary-body", "heading-h3", … Each preset carries family + size + weight +
// line-height + letter-spacing, so we never hand-pick `font-semibold`/`text-base`.
// Color stays as a token className (e.g. `text-text-02`), identical to web.
//
// Built on the RNR `text` skeleton (Slot + `asChild`).
//
// FOLLOW-UP PR — this does NOT yet fully match web's Opal `Text`. Out of scope here;
// to be reconciled in a dedicated PR:
//   • Add a typed `color?: TextColor` prop (web has it). Color is an untyped
//     `className` today, so token typos aren't caught.
//   • Canonicalize `TextFont` + `TextColor` in `@onyx-ai/shared` as the single source
//     and have both web (Opal) and mobile import them (today `TextFont` is generated
//     for mobile only; `TextColor` lives hand-written in Opal).
//   • Optionally expose `font-*` className utilities (web has `@utility font-heading-h1`)
//     via a NativeWind plugin, for className parity with web.
import { textPresets, type TextFont } from "@onyx-ai/shared/native";
import { Slot } from "@rn-primitives/slot";
import * as React from "react";
import { Text as RNText, type TextStyle } from "react-native";

import { cn } from "@/lib/utils";

interface TextProps extends React.ComponentProps<typeof RNText> {
  /** Typography preset from the shared design system (same names as web's Opal Text). */
  font?: TextFont;
  asChild?: boolean;
}

function Text({
  className,
  font = "main-ui-body",
  asChild = false,
  style,
  ...props
}: TextProps) {
  const Component = asChild ? Slot : RNText;
  // `as TextStyle`: presets type fontWeight as `string` (RN narrows it to a union);
  // the resolved values ("400"/"500"/…) are valid TextStyle at runtime.
  const preset = textPresets[font] as TextStyle;
  return (
    <Component
      style={[preset, style]}
      className={cn("text-text-04", className)}
      {...props}
    />
  );
}

export { Text, type TextFont };
