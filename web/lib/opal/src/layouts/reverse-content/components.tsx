"use client";

import "@opal/layouts/content/styles.css";
import "@opal/layouts/reverse-content/styles.css";
import { Text, type TextColor, type TextFont } from "@opal/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import {
  ContentIcon,
  contentColorStyle,
  hasIconGap,
  type ContentColor,
} from "@opal/layouts/content/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";

interface ReverseContentProps {
  /** The title's font; the icon is sized from its line, as in `Content`. */
  font?: TextFont;

  /** The icon after the title. */
  icon: IconFunctionComponent;

  /** The title. */
  title: string | RichStr;

  /** Icon and title colour pair, as in `Content`. Default: `"default"`. */
  color?: ContentColor;

  /** Overrides the title colour only, as in `Content`. */
  titleColor?: Exclude<TextColor, "inherit">;
}

/**
 * A title followed by an icon, such as a status label with its status icon.
 * The icon box is one title line tall with 2px padding, as in `Content`, and
 * the colours work the same way.
 */
function ReverseContent({
  font = "main-ui-action",
  icon,
  title,
  color = "default",
  titleColor,
}: ReverseContentProps) {
  return (
    <div
      className="opal-reverse-content"
      data-content-color={color}
      data-flush={!hasIconGap(font) || undefined}
      style={contentColorStyle(color, titleColor)}
    >
      <Text font={font} color="inherit" title={toPlainString(title)}>
        {title}
      </Text>
      <ContentIcon icon={icon} font={font} />
    </div>
  );
}

export { ReverseContent, type ReverseContentProps };
