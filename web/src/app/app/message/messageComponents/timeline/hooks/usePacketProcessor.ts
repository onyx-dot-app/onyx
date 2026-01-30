import { useRef, useState, useMemo, useCallback } from "react";
import {
  Packet,
  StreamingCitation,
  StopReason,
} from "@/app/app/services/streamingModels";
import { CitationMap } from "@/app/app/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import {
  ProcessorState,
  GroupedPacket,
  createInitialState,
  processPackets,
} from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import {
  transformPacketGroups,
  groupStepsByTurn,
  TurnGroup,
} from "@/app/app/message/messageComponents/timeline/transformers";

export interface UsePacketProcessorResult {
  // Data
  toolGroups: GroupedPacket[];
  displayGroups: GroupedPacket[];
  toolTurnGroups: TurnGroup[];
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, OnyxDocument>;

  // Status (derived from packets)
  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;
  hasSteps: boolean;
  expectedBranchesPerTurn: Map<number, number>;
  uniqueToolNames: string[];

  // Completion: stopPacketSeen && renderComplete
  isComplete: boolean;

  // Callbacks
  onRenderComplete: () => void;
  markAllToolsDisplayed: () => void;
}

/**
 * Hook for processing streaming packets in AgentMessage.
 *
 * Architecture:
 * - Processor state in ref: incremental processing, synchronous, no double render
 * - Only true UI state: renderComplete (set by callback), forceShowAnswer (override)
 * - Everything else derived from packets
 *
 * Key insight: finalAnswerComing and stopPacketSeen are DERIVED from packets,
 * not independent state. Only renderComplete needs useState.
 */
export function usePacketProcessor(
  rawPackets: Packet[],
  nodeId: number
): UsePacketProcessorResult {
  // Processor in ref: incremental, synchronous, no double render
  const stateRef = useRef<ProcessorState>(createInitialState(nodeId));

  // Only TRUE UI state: "has renderer finished?"
  const [renderComplete, setRenderComplete] = useState(false);

  // Optional override to force showing answer
  const [forceShowAnswer, setForceShowAnswer] = useState(false);

  // Reset on nodeId change
  if (stateRef.current.nodeId !== nodeId) {
    stateRef.current = createInitialState(nodeId);
    setRenderComplete(false);
    setForceShowAnswer(false);
  }

  // Track for transition detection
  const prevLastProcessed = stateRef.current.lastProcessedIndex;
  const prevFinalAnswerComing = stateRef.current.finalAnswerComing;

  // Detect stream reset (packets shrunk)
  if (prevLastProcessed > rawPackets.length) {
    stateRef.current = createInitialState(nodeId);
    setRenderComplete(false);
    setForceShowAnswer(false);
  }

  // Process packets synchronously (incremental) - only if new packets arrived
  if (rawPackets.length > stateRef.current.lastProcessedIndex) {
    stateRef.current = processPackets(stateRef.current, rawPackets);
  }

  // Reset renderComplete on tool-after-message transition
  if (prevFinalAnswerComing && !stateRef.current.finalAnswerComing) {
    setRenderComplete(false);
  }

  // Access state directly (result arrays are built in processPackets)
  const state = stateRef.current;

  // Derive displayGroups (not state!)
  const effectiveFinalAnswerComing = state.finalAnswerComing || forceShowAnswer;
  const displayGroups = useMemo(() => {
    if (effectiveFinalAnswerComing || state.toolGroups.length === 0) {
      return state.potentialDisplayGroups;
    }
    return [];
  }, [
    effectiveFinalAnswerComing,
    state.toolGroups.length,
    state.potentialDisplayGroups,
  ]);

  // Transform toolGroups to timeline format
  const toolTurnGroups = useMemo(() => {
    const allSteps = transformPacketGroups(state.toolGroups);
    return groupStepsByTurn(allSteps);
  }, [state.toolGroups]);

  // Callback reads from ref: always current value, no ref needed in component
  const onRenderComplete = useCallback(() => {
    if (stateRef.current.finalAnswerComing) {
      setRenderComplete(true);
    }
  }, []);

  const markAllToolsDisplayed = useCallback(() => {
    setForceShowAnswer(true);
  }, []);

  return {
    // Data
    toolGroups: state.toolGroups,
    displayGroups,
    toolTurnGroups,
    citations: state.citations,
    citationMap: state.citationMap,
    documentMap: state.documentMap,

    // Status (derived from packets)
    stopPacketSeen: state.stopPacketSeen,
    stopReason: state.stopReason,
    hasSteps: toolTurnGroups.length > 0,
    expectedBranchesPerTurn: state.expectedBranches,
    uniqueToolNames: state.uniqueToolNamesArray,

    // Completion: stopPacketSeen && renderComplete
    isComplete: state.stopPacketSeen && renderComplete,

    // Callbacks
    onRenderComplete,
    markAllToolsDisplayed,
  };
}
