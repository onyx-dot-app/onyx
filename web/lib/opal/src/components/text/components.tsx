import type { HTMLAttributes } from "react";

import type { RichStr, WithoutStyles } from "@opal/types";
import { cn } from "@opal/utils";
import { resolveStr } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TextFont =
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

type TextColor =
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
  | "text-dark-05";

interface TextProps
  extends WithoutStyles<
    Omit<HTMLAttributes<HTMLElement>, "color" | "children">
  > {
  /** Font preset. Default: `"main-ui-body"`. */
  font?: TextFont;

  /** Color variant. Default: `"text-04"`. */
  color?: TextColor;

  /** HTML tag to render. Default: `"span"`. */
  as?: "p" | "span" | "li" | "h1" | "h2" | "h3";

  /** Prevent text wrapping. */
  nowrap?: boolean;

  /** Truncate text to N lines with ellipsis. `1` uses simple truncation; `2+` uses `-webkit-line-clamp`. */
  maxLines?: number;

  /** Plain string or `markdown()` for inline markdown. */
  children?: string | RichStr;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

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
};

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

function Text({
  font = "main-ui-body",
  color = "text-04",
  as: Tag = "span",
  nowrap,
  maxLines,
  children,
  ...rest
}: TextProps) {
  const resolvedClassName = cn(
    "px-[2px]",
    FONT_CONFIG[font],
    COLOR_CONFIG[color],
    nowrap && "whitespace-nowrap",
    maxLines === 1 && "truncate",
    maxLines && maxLines > 1 && "overflow-hidden"
  );

  const style =
    maxLines && maxLines > 1
      ? ({
          display: "-webkit-box",
          WebkitBoxOrient: "vertical",
          WebkitLineClamp: maxLines,
        } as React.CSSProperties)
      : undefined;

  return (
    <Tag {...rest} className={resolvedClassName} style={style}>
      {children && resolveStr(children)}
    </Tag>
  );
}

export { Text, type TextProps, type TextFont, type TextColor };
