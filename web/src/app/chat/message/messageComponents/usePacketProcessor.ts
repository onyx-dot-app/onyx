import { useRef, useState } from "react";
import { Packet } from "@/app/chat/services/streamingModels";
import {
  ProcessorState,
  ProcessorResult,
  createInitialState,
  processPackets,
  getResult,
} from "./packetProcessor";

export interface UsePacketProcessorResult extends ProcessorResult {
  displayComplete: boolean;
  setDisplayComplete: (value: boolean) => void;
  // UI override for finalAnswerComing - used when all tools have been displayed
  // and we want to show the message content regardless of packet state
  setFinalAnswerComingOverride: (value: boolean) => void;
}

/**
 * Custom hook for processing streaming packets in AgentMessage.
 *
 * This hook encapsulates all packet processing logic:
 * - Incremental processing (only processes new packets)
 * - Citation extraction and deduplication
 * - Document accumulation
 * - Packet grouping by turn_index and tab_index
 * - Streaming status tracking (finalAnswerComing, stopPacketSeen, stopReason)
 * - Synthetic SECTION_END injection for graceful tool completion
 *
 * The hook uses a ref to store the processor state, which allows for:
 * - Synchronous access during render
 * - Persistence across renders without triggering re-renders
 *
 * Re-renders are triggered by:
 * - Parent updating rawPackets prop (most common)
 * - Child calling setDisplayComplete (for animation completion)
 *
 * @param rawPackets - Array of packets from the streaming response
 * @param nodeId - Unique identifier for the message node (used for reset detection)
 * @returns ProcessorResult with derived values plus displayComplete state
 */
export function usePacketProcessor(
  rawPackets: Packet[],
  nodeId: number
): UsePacketProcessorResult {
  const stateRef = useRef<ProcessorState>(createInitialState(nodeId));

  // displayComplete needs state because it's set from child callback (onComplete)
  // which needs to trigger a re-render to show feedback buttons
  const [displayComplete, setDisplayComplete] = useState(false);

  // UI override for finalAnswerComing - when all tools have been displayed,
  // we want to show the message content regardless of packet-derived state
  const [finalAnswerComingOverride, setFinalAnswerComingOverride] =
    useState(false);

  // Reset on nodeId change
  if (stateRef.current.nodeId !== nodeId) {
    stateRef.current = createInitialState(nodeId);
    setDisplayComplete(false);
    setFinalAnswerComingOverride(false);
  }

  // Track previous state to detect transitions
  const prevLastProcessed = stateRef.current.lastProcessedIndex;
  const prevFinalAnswerComing = stateRef.current.finalAnswerComing;

  // Process packets (incremental - only processes new packets)
  stateRef.current = processPackets(stateRef.current, rawPackets);

  // Detect tool-after-message scenario: if finalAnswerComing went from true to false,
  // it means a tool packet arrived after message packets. Reset displayComplete to
  // prevent showing feedback buttons while tools are still executing.
  if (prevFinalAnswerComing && !stateRef.current.finalAnswerComing) {
    setDisplayComplete(false);
  }

  // Detect stream reset (packets array shrunk) - processPackets resets state internally,
  // but we also need to reset React state that lives outside the processor
  if (prevLastProcessed > rawPackets.length) {
    setDisplayComplete(false);
    setFinalAnswerComingOverride(false);
  }

  // Get derived result
  const result = getResult(stateRef.current);

  // Combine packet-derived finalAnswerComing with UI override
  // UI override is set when all tools have been displayed
  const finalAnswerComing =
    result.finalAnswerComing || finalAnswerComingOverride;

  return {
    ...result,
    finalAnswerComing,
    displayComplete,
    setDisplayComplete,
    setFinalAnswerComingOverride,
  };
}
