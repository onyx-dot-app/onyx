"use client";

import React, {
  createContext,
  useContext,
  useState,
  useRef,
  useLayoutEffect,
} from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  TooltipProvider,
} from "@/components/ui/tooltip";
import Text, { TextProps } from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

interface TruncatedContextValue {
  isTruncated: boolean;
  visibleRef: React.RefObject<HTMLDivElement>;
  hiddenRef: React.RefObject<HTMLDivElement>;
}

const TruncatedContext = createContext<TruncatedContextValue | null>(null);

function useTruncatedContext() {
  const context = useContext(TruncatedContext);
  if (!context) {
    throw new Error(
      "Truncated components must be used within a TruncatedProvider"
    );
  }
  return context;
}

interface TruncatedProviderProps {
  children: React.ReactNode;
}

export function TruncatedProvider({ children }: TruncatedProviderProps) {
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

  return (
    <TruncatedContext.Provider value={{ isTruncated, visibleRef, hiddenRef }}>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div>{children}</div>
          </TooltipTrigger>
        </Tooltip>
      </TooltipProvider>
    </TruncatedContext.Provider>
  );
}

export function TruncatedTrigger({ className, children, ...rest }: TextProps) {
  const { visibleRef, hiddenRef } = useTruncatedContext();

  const text = (
    <Text
      className={cn("line-clamp-1 break-all text-left", className)}
      {...rest}
    >
      {children}
    </Text>
  );

  return (
    <>
      <div
        ref={visibleRef}
        className="flex-grow overflow-hidden text-left w-full"
      >
        {text}
        {/* {isLoading ? loadingAnimation : text} */}
      </div>

      {/* Hide offscreen to measure full text width */}
      <div
        ref={hiddenRef}
        className="fixed left-[-9999px] top-[0rem] whitespace-nowrap pointer-events-none opacity-0"
        aria-hidden="true"
      >
        {text}
      </div>
    </>
  );
}

interface TruncatedContentProps {
  side?: "top" | "right" | "bottom" | "left";
  sideOffset?: number;
  disable?: boolean;
  children?: React.ReactNode;
}

export function TruncatedContent({
  side = "right",
  sideOffset,
  disable,
  children,
}: TruncatedContentProps) {
  const { isTruncated } = useTruncatedContext();

  if (disable || !isTruncated) return null;

  return (
    <TooltipContent side={side} sideOffset={sideOffset}>
      {typeof children === "string" ? (
        <Text inverted>{children}</Text>
      ) : (
        children
      )}
    </TooltipContent>
  );
}
