"use client";

import React, { useState, useRef, useLayoutEffect } from "react";
import { TextProps } from "@/refresh-components/texts/Text";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  TooltipProvider,
} from "@/components/ui/tooltip";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

/**
 * Hook to detect if text is truncated by comparing visible width vs full width
 */
function useTruncated(children: React.ReactNode) {
  const [isTruncated, setIsTruncated] = useState(false);
  const visibleRef = useRef<HTMLDivElement>(null);
  const hiddenRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    function checkTruncation() {
      if (visibleRef.current && hiddenRef.current) {
        const visibleWidth = visibleRef.current.offsetWidth;
        const fullTextWidth = hiddenRef.current.offsetWidth;
        setIsTruncated(fullTextWidth > visibleWidth);
      }
    }

    // Use a small delay to ensure DOM is ready
    const timeoutId = setTimeout(checkTruncation, 0);

    window.addEventListener("resize", checkTruncation);
    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("resize", checkTruncation);
    };
  }, [children]);

  return { isTruncated, visibleRef, hiddenRef };
}

export interface TruncatedProps extends TextProps {
  side?: "top" | "right" | "bottom" | "left";
  sideOffset?: number;
  disable?: boolean;
}

/**
 * Renders passed in text on a single line. If text is truncated,
 * shows a tooltip on hover with the full text.
 */
export default function Truncated({
  side = "top",
  sideOffset,
  disable,
  children,
  className,
  ...rest
}: TruncatedProps) {
  const { isTruncated, visibleRef, hiddenRef } = useTruncated(children);

  const text = (
    <Text
      className={cn("line-clamp-1 break-all text-left", className)}
      {...rest}
    >
      {children}
    </Text>
  );

  const showTooltip = !disable && isTruncated;

  return (
    <TooltipProvider>
      <Tooltip>
        <div
          ref={visibleRef}
          className="flex-grow overflow-hidden text-left w-full"
        >
          <TooltipTrigger asChild>
            <div>{text}</div>
          </TooltipTrigger>
        </div>

        {/* Hide offscreen to measure full text width */}
        <div
          ref={hiddenRef}
          className="fixed left-[-9999px] top-[0rem] whitespace-nowrap pointer-events-none opacity-0"
          aria-hidden="true"
        >
          {text}
        </div>

        {showTooltip && (
          <TooltipContent side={side} sideOffset={sideOffset}>
            {typeof children === "string" ? (
              <Text inverted>{children}</Text>
            ) : (
              children
            )}
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}
