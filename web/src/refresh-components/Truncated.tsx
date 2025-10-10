import React, {
  useState,
  useRef,
  useLayoutEffect,
  createContext,
  useContext,
} from "react";
import SimpleTooltip from "./SimpleTooltip";
import Text, { TextProps } from "./Text";
import { cn } from "@/lib/utils";

interface TruncatedProps extends TextProps {
  side?: "top" | "right" | "bottom" | "left";
  offset?: number;
  disable?: boolean;
}

interface TruncatedContextValue {
  isTruncated: boolean;
  setIsTruncated: (value: boolean) => void;
  isLoading: boolean;
  setIsLoading: (value: boolean) => void;
}

const TruncatedContext = createContext<TruncatedContextValue | null>(null);

export function TruncatedProvider({ children }: { children: React.ReactNode }) {
  const [isTruncated, setIsTruncated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  return (
    <TruncatedContext.Provider
      value={{ isTruncated, setIsTruncated, isLoading, setIsLoading }}
    >
      {children}
    </TruncatedContext.Provider>
  );
}

/**
 * Renders passed in text on a single line. If text is truncated,
 * shows a tooltip on hover with the full text.
 */
export default function Truncated({
  side = "top",
  offset = 5,
  disable,

  className,
  children,
  ...rest
}: TruncatedProps) {
  const context = useContext(TruncatedContext);

  const [localIsTruncated, setLocalIsTruncated] = useState(false);
  const [localIsLoading, setLocalIsLoading] = useState(true);

  const isTruncated = context?.isTruncated ?? localIsTruncated;
  const setIsTruncated = context?.setIsTruncated ?? setLocalIsTruncated;
  const isLoading = context?.isLoading ?? localIsLoading;
  const setIsLoading = context?.setIsLoading ?? setLocalIsLoading;

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

  const tooltip =
    !disable && isTruncated && !isLoading
      ? typeof children === "string"
        ? children
        : undefined
      : undefined;

  const loadingAnimation = (
    <div
      className={cn(
        "h-[1.2rem] w-full bg-background-tint-03 rounded animate-pulse",
        className
      )}
    />
  );

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
      <SimpleTooltip tooltip={tooltip}>
        <div
          ref={visibleRef}
          className="flex-grow overflow-hidden text-left w-full"
        >
          {isLoading ? loadingAnimation : text}
        </div>
      </SimpleTooltip>

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
