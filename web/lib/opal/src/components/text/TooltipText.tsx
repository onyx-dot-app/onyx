"use client";

import { useCallback, useState } from "react";
import { Tooltip } from "@opal/components/tooltip/components";
import { TextElement, type TextProps } from "@opal/components/text/components";
import useOverflow from "@opal/hooks/useOverflow";
import { isRichNodes } from "@opal/utils";

/**
 * `Text` with its one tooltip: `tooltip` on every hover, or else, with
 * `overflowTooltip`, the full text while the clamp cuts it.
 */
function TooltipText({ tooltip, overflowTooltip, ref, ...props }: TextProps) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  // Measures only when the overflow decides the tooltip.
  const overflowing = useOverflow(
    tooltip === undefined && overflowTooltip ? element : null
  );
  // Returns a cleanup, so React no longer calls it with `null`: the cleanup
  // clears the element and runs the caller's cleanup, or else hands the
  // caller its `null`.
  const setRef = useCallback(
    (node: HTMLElement | null) => {
      setElement(node);
      const cleanup = ref?.(node);
      return () => {
        setElement(null);
        if (typeof cleanup === "function") cleanup();
        else ref?.(null);
      };
    },
    [ref]
  );

  const content =
    tooltip ??
    (props.children === undefined || isRichNodes(props.children)
      ? undefined
      : props.children);

  // Suppressed rather than dropped: dropping the tooltip changes the tree's
  // shape, which remounts the text and loses the element the measure reads.
  return (
    <Tooltip
      tooltip={content}
      suppressed={tooltip === undefined && !overflowing}
      side="top"
      align={tooltip === undefined ? "start" : "center"}
    >
      <TextElement {...props} ref={setRef} />
    </Tooltip>
  );
}

export { TooltipText };
