import { useEffect, useState } from "react";
import { Packet } from "@/app/chat/services/streamingModels";

// Control the rate of packet streaming (packets per second)
const PACKET_DELAY_MS = 10;

interface UsePacketAnimationAndCollapseOptions {
  /** Array of packets to animate */
  packets: Packet[];
  /** Whether animation is enabled */
  animate: boolean;
  /** Whether the content is complete (has SECTION_END) */
  isComplete: boolean;
  /** Callback to invoke when animation and completion are done */
  onComplete: () => void;
  /** Optional: prevent double-calling onComplete (for renderers that need it) */
  preventDoubleComplete?: boolean;
}

interface UsePacketAnimationAndCollapseReturn {
  /** Number of packets currently displayed (or -1 if showing all) */
  displayedPacketCount: number;
  /** Whether the content is expanded */
  isExpanded: boolean;
  /** Function to toggle expansion state */
  toggleExpanded: () => void;
}

/**
 * Hook that handles packet animation and auto-collapse behavior.
 *
 * Features:
 * - Gradually displays packets with configurable delay
 * - Auto-collapses when content is complete
 * - Calls onComplete when animation finishes and content is complete
 * - Manages expansion state for collapsible content
 */
export function usePacketAnimationAndCollapse({
  packets,
  animate,
  isComplete,
  onComplete,
  preventDoubleComplete = false,
}: UsePacketAnimationAndCollapseOptions): UsePacketAnimationAndCollapseReturn {
  // If we're animating, start with 1 packet, otherwise show all
  const initialPacketCount = animate ? (packets.length > 0 ? 1 : 0) : -1;

  const [displayedPacketCount, setDisplayedPacketCount] =
    useState(initialPacketCount);
  const [isExpanded, setIsExpanded] = useState(true);
  const [hasAutoCollapsed, setHasAutoCollapsed] = useState(false);
  const [hasCalledComplete, setHasCalledComplete] = useState(false);

  // Auto-collapse when content is complete
  useEffect(() => {
    if (isComplete && !hasAutoCollapsed) {
      setIsExpanded(false);
      setHasAutoCollapsed(true);
    }
  }, [isComplete, hasAutoCollapsed]);

  // Animation effect - gradually increase displayed packets
  useEffect(() => {
    if (!animate) {
      setDisplayedPacketCount(-1);
      return;
    }

    if (displayedPacketCount >= 0 && displayedPacketCount < packets.length) {
      const timer = setTimeout(() => {
        setDisplayedPacketCount((prev) => Math.min(prev + 1, packets.length));
      }, PACKET_DELAY_MS);

      return () => clearTimeout(timer);
    }
  }, [animate, displayedPacketCount, packets.length]);

  // Reset displayed count when packet array changes significantly
  useEffect(() => {
    if (animate && packets.length < displayedPacketCount) {
      setDisplayedPacketCount(packets.length > 0 ? 1 : 0);
    }
  }, [animate, packets.length, displayedPacketCount]);

  // Call onComplete when done (animation finished and content complete)
  useEffect(() => {
    if (isComplete) {
      // If animation is still in progress, wait for it to finish
      if (
        animate &&
        displayedPacketCount >= 0 &&
        displayedPacketCount < packets.length
      ) {
        return;
      }

      // Prevent double-calling if requested
      if (preventDoubleComplete && hasCalledComplete) {
        return;
      }

      if (preventDoubleComplete) {
        setHasCalledComplete(true);
      }
      onComplete();
    }
  }, [
    isComplete,
    onComplete,
    animate,
    displayedPacketCount,
    packets.length,
    preventDoubleComplete,
    hasCalledComplete,
  ]);

  const toggleExpanded = () => {
    setIsExpanded((prev) => !prev);
  };

  return {
    displayedPacketCount,
    isExpanded,
    toggleExpanded,
  };
}
