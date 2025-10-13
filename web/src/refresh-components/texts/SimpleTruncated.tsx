import React from "react";
import { TextProps } from "@/refresh-components/texts/Text";
import {
  TruncatedProvider,
  TruncatedTrigger,
  TruncatedContent,
} from "@/refresh-components/texts/Truncated";

interface SimpleTruncatedProps extends TextProps {
  side?: "top" | "right" | "bottom" | "left";
  sideOffset?: number;
  disable?: boolean;
}

/**
 * Renders passed in text on a single line. If text is truncated,
 * shows a tooltip on hover with the full text.
 */
export default function SimpleTruncated({
  side = "top",
  sideOffset,
  disable,
  className,
  children,
  ...rest
}: SimpleTruncatedProps) {
  return (
    <TruncatedProvider>
      <TruncatedTrigger className={className} {...rest}>
        {children}
      </TruncatedTrigger>
      <TruncatedContent
        side={side}
        sideOffset={sideOffset}
        disable={disable}
        {...rest}
      >
        {children}
      </TruncatedContent>
    </TruncatedProvider>
  );
}
