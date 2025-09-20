import React, { useState, useRef, useLayoutEffect } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Text, { TextProps } from "./Text";

interface TruncatedProps extends TextProps {
  tooltipSide?: "top" | "right" | "bottom" | "left";
  tooltipSideOffset?: number;
  disableTooltip?: boolean;
}

/**
 * Renders passed in text on a single line. If text is truncated,
 * shows a tooltip on hover with the full text.
 */
export default function Truncated({
  tooltipSide = "top",
  tooltipSideOffset = 5,
  disableTooltip,
  children,
  ...rest
}: TruncatedProps) {
  const [isTruncated, setIsTruncated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const visibleRef = useRef<HTMLDivElement>(null);
  const hiddenRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    function checkTruncation() {
      if (visibleRef.current && hiddenRef.current) {
        const visibleWidth = visibleRef.current.offsetWidth;
        const fullTextWidth = hiddenRef.current.offsetWidth;
        setIsTruncated(fullTextWidth > visibleWidth);
        setIsLoading(false);
      }
    }

    // Reset loading state when children change
    setIsLoading(true);

    // Use a small delay to ensure DOM is ready
    const timeoutId = setTimeout(checkTruncation, 0);

    window.addEventListener("resize", checkTruncation);
    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("resize", checkTruncation);
    };
  }, []);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            ref={visibleRef}
            className="flex-grow overflow-hidden text-left w-full"
          >
            {isLoading ? (
              <div
                className={`h-[1.2rem] w-full bg-background-tint-03 rounded animate-pulse ${rest.className}`}
              />
            ) : (
              <Text
                className={`line-clamp-1 break-all text-left ${rest.className}`}
                {...rest}
              >
                {children}
              </Text>
            )}
          </div>
        </TooltipTrigger>

        {/* Hide offscreen to measure full text width */}
        <div
          ref={hiddenRef}
          className="fixed left-[-9999px] top-[0rem] whitespace-nowrap pointer-events-none opacity-0"
          aria-hidden="true"
        >
          {children}
        </div>

        {!disableTooltip && isTruncated && !isLoading && (
          <TooltipContent side={tooltipSide} sideOffset={tooltipSideOffset}>
            <Text>{children}</Text>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}
