import { useRef, useCallback } from "react";

export interface UseScrollManagementProps {
  autoScrollEnabled: boolean;
}

export function useScrollManagement({
  autoScrollEnabled,
}: UseScrollManagementProps) {
  // UI REFS: DOM element references for scroll management and layout
  const scrollableDivRef = useRef<HTMLDivElement>(null); // Main scrollable chat container
  const lastMessageRef = useRef<HTMLDivElement>(null); // Reference to last message for scroll positioning
  const inputRef = useRef<HTMLDivElement>(null); // Input bar container for height calculations
  const endDivRef = useRef<HTMLDivElement>(null); // End marker for scroll-to-bottom functionality
  const endPaddingRef = useRef<HTMLDivElement>(null); // Bottom padding that adjusts with input height

  const previousHeight = useRef<number>(
    inputRef.current?.getBoundingClientRect().height!
  );
  const scrollDist = useRef<number>(0);

  // UI REF: Prevents scroll conflicts during animations
  const waitForScrollRef = useRef(false);

  // UI FUNCTION: Handle input bar resize with smooth scrolling and padding adjustments
  const handleInputResize = useCallback(() => {
    setTimeout(() => {
      if (
        inputRef.current &&
        lastMessageRef.current &&
        !waitForScrollRef.current
      ) {
        const newHeight: number =
          inputRef.current?.getBoundingClientRect().height!;
        const heightDifference = newHeight - previousHeight.current;
        if (
          previousHeight.current &&
          heightDifference != 0 &&
          endPaddingRef.current &&
          scrollableDivRef &&
          scrollableDivRef.current
        ) {
          endPaddingRef.current.style.transition = "height 0.3s ease-out";
          endPaddingRef.current.style.height = `${Math.max(
            newHeight - 50,
            0
          )}px`;

          if (autoScrollEnabled) {
            scrollableDivRef?.current.scrollBy({
              left: 0,
              top: Math.max(heightDifference, 0),
              behavior: "smooth",
            });
          }
        }
        previousHeight.current = newHeight;
      }
    }, 100);
  }, [autoScrollEnabled]);

  // UI FUNCTION: Scroll chat to bottom with smooth animation and visibility checks
  const clientScrollToBottom = useCallback((fast?: boolean) => {
    waitForScrollRef.current = true;

    setTimeout(() => {
      if (!endDivRef.current || !scrollableDivRef.current) {
        console.error("endDivRef or scrollableDivRef not found");
        return;
      }

      const rect = endDivRef.current.getBoundingClientRect();
      const isVisible = rect.top >= 0 && rect.bottom <= window.innerHeight;

      if (isVisible) return;

      // Check if all messages are currently rendered
      // If all messages are already rendered, scroll immediately
      endDivRef.current.scrollIntoView({
        behavior: fast ? "auto" : "smooth",
      });
    }, 50);

    // Reset waitForScrollRef after 1.5 seconds
    setTimeout(() => {
      waitForScrollRef.current = false;
    }, 1500);
  }, []);

  return {
    scrollableDivRef,
    lastMessageRef,
    inputRef,
    endDivRef,
    endPaddingRef,
    waitForScrollRef,
    scrollDist,
    handleInputResize,
    clientScrollToBottom,
  };
}
