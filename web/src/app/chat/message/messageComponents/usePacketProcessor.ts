import { useRef, useState, useMemo, useCallback } from "react";
import {
  Packet,
  StreamingCitation,
  StopReason,
} from "@/app/chat/services/streamingModels";
import { CitationMap } from "@/app/chat/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import {
  ProcessorState,
  GroupedPacket,
  createInitialState,
  processPackets,
  getResult,
} from "./packetProcessor";
import {
  transformPacketGroups,
  groupStepsByTurn,
  TurnGroup,
} from "./timeline/transformers";

export interface UsePacketProcessorResult {
  // Citations & Documents
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, OnyxDocument>;

  // Pre-categorized and transformed groups
  toolGroups: GroupedPacket[];
  toolTurnGroups: TurnGroup[];
  displayGroups: GroupedPacket[];
  hasSteps: boolean;

  // Streaming status
  finalAnswerComing: boolean;
  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;
  expectedBranchesPerTurn: Map<number, number>;

  // UI state
  displayComplete: boolean;
  setDisplayComplete: (value: boolean) => void;
  /** Call when UI has finished displaying all tools to show message content */
  markAllToolsDisplayed: () => void;
}

/**
 * Custom hook for processing streaming packets in AgentMessage.
 *
 * This hook encapsulates all packet processing logic:
 * - Incremental processing (only processes new packets)
 * - Citation extraction and deduplication
 * - Document accumulation
 * - Packet grouping by turn_index and tab_index with pre-categorization
 * - Timeline transformation for tool groups
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
 * - UI calling markAllToolsDisplayed (to show message content)
 *
 * @param rawPackets - Array of packets from the streaming response
 * @param nodeId - Unique identifier for the message node (used for reset detection)
 * @returns Processed data ready for rendering in AgentMessage
 */
export function usePacketProcessor(
  rawPackets: Packet[],
  nodeId: number
): UsePacketProcessorResult {
  const stateRef = useRef<ProcessorState>(createInitialState(nodeId));

  // displayComplete needs state because it's set from child callback (onComplete)
  // which needs to trigger a re-render to show feedback buttons
  const [displayComplete, setDisplayComplete] = useState(false);

  // Track when UI has marked all tools as displayed
  // This replaces the previous setFinalAnswerComingOverride with a cleaner API
  const [allToolsDisplayedByUI, setAllToolsDisplayedByUI] = useState(false);

  // Reset on nodeId change
  if (stateRef.current.nodeId !== nodeId) {
    stateRef.current = createInitialState(nodeId);
    setDisplayComplete(false);
    setAllToolsDisplayedByUI(false);
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
    setAllToolsDisplayedByUI(false);
  }

  // Get derived result from processor
  const result = getResult(stateRef.current);

  // Combine packet-derived finalAnswerComing with UI override
  const finalAnswerComing = result.finalAnswerComing || allToolsDisplayedByUI;

  // Compute displayGroups: show when finalAnswerComing is true OR no tools exist
  const displayGroups = useMemo(() => {
    if (finalAnswerComing || result.toolGroups.length === 0) {
      return result.potentialDisplayGroups;
    }
    return [];
  }, [
    finalAnswerComing,
    result.toolGroups.length,
    result.potentialDisplayGroups,
  ]);

  // Transform toolGroups to timeline format (uses iconRegistry for JSX icons)
  const toolTurnGroups = useMemo(() => {
    const allSteps = transformPacketGroups(result.toolGroups);
    return groupStepsByTurn(allSteps);
  }, [result.toolGroups]);

  // Stable callback for marking all tools displayed
  const markAllToolsDisplayed = useCallback(() => {
    setAllToolsDisplayedByUI(true);
  }, []);

  return {
    citations: result.citations,
    citationMap: result.citationMap,
    documentMap: result.documentMap,
    toolGroups: result.toolGroups,
    toolTurnGroups,
    displayGroups,
    hasSteps: toolTurnGroups.length > 0,
    finalAnswerComing,
    stopPacketSeen: result.stopPacketSeen,
    stopReason: result.stopReason,
    expectedBranchesPerTurn: result.expectedBranchesPerTurn,
    displayComplete,
    setDisplayComplete,
    markAllToolsDisplayed,
  };
}
