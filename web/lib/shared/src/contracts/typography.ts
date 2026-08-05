/**
 * Typography type unions shared by web (Opal `Text`) and mobile (`Text`).
 *
 * They live in this neutral contracts module — not `@onyx-ai/shared/native`, which is
 * RN-only runtime (`varsLight`/`varsDark`/`textPresets`). The generated `native.d.ts`
 * imports `TextFont` from here so `textPresets` stays typed by this one union.
 *
 * `TextFont` mirrors the preset names in `tokens/typography-presets.json` — keep it in
 * sync when presets change.
 */

export type TextFont =
  | "heading-h1"
  | "heading-h2"
  | "heading-h3"
  | "heading-h3-muted"
  | "main-content-body"
  | "main-content-muted"
  | "main-content-emphasis"
  | "main-content-mono"
  | "main-ui-body"
  | "main-ui-muted"
  | "main-ui-action"
  | "main-ui-mono"
  | "secondary-body"
  | "secondary-action"
  | "secondary-mono"
  | "secondary-mono-label"
  | "figure-small-label"
  | "figure-small-value"
  | "figure-keystroke";

/** `inherit` is a sentinel (renders no color class); the rest are token names. */
export type TextColor =
  | "inherit"
  | "text-01"
  | "text-02"
  | "text-03"
  | "text-04"
  | "text-05"
  | "text-inverted-01"
  | "text-inverted-02"
  | "text-inverted-03"
  | "text-inverted-04"
  | "text-inverted-05"
  | "text-light-03"
  | "text-light-05"
  | "text-dark-03"
  | "text-dark-05"
  | "status-error-01"
  | "status-error-02"
  | "status-error-05"
  | "status-success-01"
  | "status-success-02"
  | "status-success-05";
