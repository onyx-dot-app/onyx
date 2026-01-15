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

  // Process packets synchronously (incremental)
  stateRef.current = processPackets(stateRef.current, rawPackets);

  // Reset renderComplete on tool-after-message transition
  if (prevFinalAnswerComing && !stateRef.current.finalAnswerComing) {
    setRenderComplete(false);
  }

  // Get derived result
  const result = getResult(stateRef.current);

  // Derive displayGroups (not state!)
  const effectiveFinalAnswerComing =
    result.finalAnswerComing || forceShowAnswer;
  const displayGroups = useMemo(() => {
    if (effectiveFinalAnswerComing || result.toolGroups.length === 0) {
      return result.potentialDisplayGroups;
    }
    return [];
  }, [
    effectiveFinalAnswerComing,
    result.toolGroups.length,
    result.potentialDisplayGroups,
  ]);

  // Transform toolGroups to timeline format
  const toolTurnGroups = useMemo(() => {
    const allSteps = transformPacketGroups(result.toolGroups);
    return groupStepsByTurn(allSteps);
  }, [result.toolGroups]);

  // Callback reads from ref: always current value, no ref needed in component
  const onRenderComplete = useCallback(() => {
    if (stateRef.current.finalAnswerComing) {
      setRenderComplete(true);
    }
  }, []);

  const markAllToolsDisplayed = useCallback(() => {
    setForceShowAnswer(true);
  }, []);

  console.log("toolTurnGroups", toolTurnGroups);
  console.log("displayGroups", displayGroups);
  console.log("result.toolGroups", result.toolGroups);

  return {
    // Data
    toolGroups: result.toolGroups,
    displayGroups,
    toolTurnGroups,
    citations: result.citations,
    citationMap: result.citationMap,
    documentMap: result.documentMap,

    // Status (derived from packets)
    stopPacketSeen: result.stopPacketSeen,
    stopReason: result.stopReason,
    hasSteps: toolTurnGroups.length > 0,
    expectedBranchesPerTurn: result.expectedBranchesPerTurn,

    // Completion: stopPacketSeen && renderComplete
    isComplete: result.stopPacketSeen && renderComplete,

    // Callbacks
    onRenderComplete,
    markAllToolsDisplayed,
  };
}
