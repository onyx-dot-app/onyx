import React, {
  useState,
  useRef,
  useLayoutEffect,
  HTMLAttributes,
} from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface TruncatedTextProps extends HTMLAttributes<HTMLSpanElement> {
  text: string;
  tooltipClassName?: string;
  tooltipSide?: "top" | "right" | "bottom" | "left";
  tooltipSideOffset?: number;
}

/**
 * Renders passed in text on a single line. If text is truncated,
 * shows a tooltip on hover with the full text.
 */
export function TruncatedText({
  text,
  tooltipClassName,
  tooltipSide = "right",
  tooltipSideOffset = 5,
  className = "",
  ...rest
}: TruncatedTextProps) {
  const [isTruncated, setIsTruncated] = useState(false);
  const visibleRef = useRef<HTMLSpanElement>(null);
  const hiddenRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    function checkTruncation() {
      if (visibleRef.current && hiddenRef.current) {
        const visibleWidth = visibleRef.current.offsetWidth;
        const fullTextWidth = hiddenRef.current.offsetWidth;
        setIsTruncated(fullTextWidth > visibleWidth);
      }
    }

    checkTruncation();
    window.addEventListener("resize", checkTruncation);
    return () => window.removeEventListener("resize", checkTruncation);
  }, [text]);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            ref={visibleRef}
            // Ensure the text can actually truncate via line-clamp or overflow
            className={`line-clamp-1 break-all flex-grow ${className}`}
            {...rest}
          >
            {text}
          </span>
        </TooltipTrigger>
        {/* Hide offscreen to measure full text width */}
        <span
          ref={hiddenRef}
          className="absolute left-[-9999px] whitespace-nowrap pointer-events-none"
          aria-hidden="true"
        >
          {text}
        </span>
        {isTruncated && (
          <TooltipContent
            side={tooltipSide}
            sideOffset={tooltipSideOffset}
            className={tooltipClassName}
          >
            <p className="text-xs max-w-[200px] whitespace-normal break-words">
              {text}
            </p>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}
