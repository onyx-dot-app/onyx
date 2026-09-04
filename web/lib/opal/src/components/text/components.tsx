import type { HTMLAttributes } from "react";
// Canonical TextFont/TextColor unions, shared with mobile via the neutral
// @onyx-ai/shared/contracts (not the RN-only /native).
import type { TextColor, TextFont } from "@onyx-ai/shared/contracts";
import type { RichNodes, RichStr, WithoutStyles } from "@opal/types";
import { cn, isRichNodes } from "@opal/utils";
import { resolveStr } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TextProps extends WithoutStyles<
  Omit<HTMLAttributes<HTMLElement>, "color" | "children">
> {
  /** Font preset. Default: `"main-ui-body"`. */
  font?: TextFont;

  /** Color variant. Default: `"text-04"`. */
  color?: TextColor;

  /** HTML tag to render. Default: `"span"`. */
  as?: "p" | "span" | "li" | "h1" | "h2" | "h3";

  /**
   * How this text wraps. Ordinary wrapping only breaks at whitespace, so a
   * URL, an identifier or any single long token overflows its container
   * instead of wrapping.
   *
   * - `"whitespace-nowrap"` — do not wrap at all; the text stays on one line.
   * - `"wrap-normal"` — the CSS default: break at whitespace only, and let a
   *   long run overflow. Spell it out to override an inherited value, since
   *   `overflow-wrap` inherits and omitting this prop cannot undo an
   *   ancestor's.
   * - `"wrap-break-word"` — break only when the run would otherwise overflow.
   * - `"wrap-anywhere"` — as above, and count the break when min-content is
   *   measured, so the element can shrink as a flex item.
   * - `"break-all"` — break between any two characters.
   * - `"break-keep"` — never break within a word (CJK).
   */
  wordWrap?:
    | "whitespace-nowrap"
    | "wrap-normal"
    | "wrap-break-word"
    | "wrap-anywhere"
    | "break-all"
    | "break-keep";

  /**
   * How the text sits within its own box. Logical values, so they follow the
   * reading direction rather than the screen: `"text-start"` is left in an
   * LTR locale and right in an RTL one.
   *
   * This aligns the text inside the element `Text` renders. Positioning that
   * element within its parent is the parent's business — see the note on
   * layout below.
   */
  textPosition?: "text-start" | "text-center" | "text-end" | "text-justify";

  /** Truncate text to N lines with ellipsis. `1` uses simple truncation; `2+` uses `-webkit-line-clamp`. */
  maxLines?: number;

  /**
   * Strike the text through. This is a presentational state (e.g. an option
   * that is switched off), so it stays a prop rather than `~~` in the content:
   * the caller keeps passing the plain string, and no escaping is needed.
   */
  strikethrough?: boolean;

  /**
   * Plain string, `markdown()` for inline markdown, or `richNodes()` for
   * sentences that embed inline components (e.g. next-intl `t.rich` output).
   */
  children?: string | RichStr | RichNodes;
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
  "status-error-01": "text-status-error-01",
  "status-error-02": "text-status-error-02",
  "status-error-05": "text-status-error-05",
  "status-success-01": "text-status-success-01",
  "status-success-02": "text-status-success-02",
  "status-success-05": "text-status-success-05",
};

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

function Text({
  font = "main-ui-body",
  color = "text-04",
  as: Tag = "span",
  wordWrap,
  textPosition,
  maxLines,
  strikethrough,
  children,
  ...rest
}: TextProps) {
  const resolvedClassName = cn(
    "px-[2px]",
    FONT_CONFIG[font],
    COLOR_CONFIG[color],
    wordWrap,
    textPosition,
    maxLines === 1 && "truncate",
    maxLines && maxLines > 1 && "overflow-hidden",
    strikethrough && "line-through"
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
      {children &&
        (isRichNodes(children) ? children.nodes : resolveStr(children))}
    </Tag>
  );
}

export { Text, type TextProps };
// Re-export the shared unions so existing `@opal/components` consumers are unchanged.
export type { TextFont, TextColor };
