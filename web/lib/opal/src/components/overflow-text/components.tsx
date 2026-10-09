"use client";

import { useState } from "react";
import { Text, type TextProps } from "@opal/components/text/components";
import { Tooltip } from "@opal/components/tooltip/components";
import useOverflow from "@opal/hooks/useOverflow";
import type { DistributiveOmit, RichStr } from "@opal/types";

type OverflowTextProps = DistributiveOmit<
  TextProps,
  "children" | "maxLines" | "ref"
> & {
  /** The text. It also fills the tooltip, so it stays string-derivable. */
  children: string | RichStr;
  /** Lines shown before the text is cut with an ellipsis. Default: `1`. */
  maxLines?: number;
};

/**
 * `Text` clamped to `maxLines`. While the clamp cuts the text, hovering it
 * shows the full text in a tooltip above it, aligned to the text's start (left
 * in LTR, right in RTL); text that fits gets no tooltip.
 */
function OverflowText({
  children,
  maxLines = 1,
  ...textProps
}: OverflowTextProps) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const overflowing = useOverflow(element);

  return (
    <Tooltip
      tooltip={overflowing ? children : undefined}
      side="top"
      align="start"
    >
      <Text {...textProps} ref={setElement} maxLines={maxLines}>
        {children}
      </Text>
    </Tooltip>
  );
}

export { OverflowText, type OverflowTextProps };
