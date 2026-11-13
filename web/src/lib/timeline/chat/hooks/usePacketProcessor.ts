/* oxlint-disable react-doctor/no-ref-current-in-render -- render-phase
   incremental processing is the core design: the packet cursor makes
   replays idempotent and consumers need the state in the same commit. */
import { useRef, useState, useMemo, useCallback } from "react";
import {
  Packet,
  PacketType,
  StreamingCitation,
  StopReason,
} from "@/app/app/services/streamingModels";
import { CitationMap } from "@/app/app/types";
import { OnyxDocument } from "@/lib/search/types";
import {
  ProcessorState,
  PlacedImage,
  GroupedPacket,
  createInitialState,
  processPackets,
} from "@/lib/timeline/chat/hooks/packetProcessor";
import {
  expandCodeModeSteps,
  transformPacketGroups,
  groupStepsByTurn,
  TurnGroup,
} from "@/lib/timeline/chat/transformers";

export interface UsePacketProcessorResult {
  // Data
  toolGroups: GroupedPacket[];
  displayGroups: GroupedPacket[];
  toolTurnGroups: TurnGroup[];
  /** A code mode program works between tool calls; it has no step. */
  codeModeWorking: boolean;
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, OnyxDocument>;

  // Status (derived from packets)
  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;
  /** Packets through the latest accepted user message. */
  acceptedPacketCount: number;
  generatedImages: PlacedImage[];
  // Whether final answer is coming (MESSAGE_START seen)
  finalAnswerComing: boolean;
  // Tool processing duration from backend (via MESSAGE_START packet)
  toolProcessingDuration: number | undefined;

  // Completion: stopped, and the answer (if any) finished rendering
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
  const prevNextPacketIndex = stateRef.current.nextPacketIndex;
  const prevFinalAnswerComing = stateRef.current.finalAnswerComing;
  const previousDisplayGroup = stateRef.current.potentialDisplayGroups.at(-1);

  // Detect stream reset (packets shrunk)
  if (prevNextPacketIndex > rawPackets.length) {
    stateRef.current = createInitialState(nodeId);
    setRenderComplete(false);
    setForceShowAnswer(false);
  }

  // Process packets synchronously (incremental) - only if new packets arrived
  if (rawPackets.length > stateRef.current.nextPacketIndex) {
    stateRef.current = processPackets(stateRef.current, rawPackets);
  }

  // Each new answer must finish rendering before the response toolbar appears.
  const latestDisplayGroup = stateRef.current.potentialDisplayGroups.at(-1);
  if (
    (prevFinalAnswerComing && !stateRef.current.finalAnswerComing) ||
    previousDisplayGroup?.turn_index !== latestDisplayGroup?.turn_index ||
    previousDisplayGroup?.tab_index !== latestDisplayGroup?.tab_index
  ) {
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
    const acceptedThroughTurn =
      state.potentialDisplayGroups.findLast(
        (group) => group.packets[0]?.obj.type === PacketType.USER_MESSAGE
      )?.turn_index ?? -1;
    return state.potentialDisplayGroups.filter(
      (group) => group.turn_index <= acceptedThroughTurn
    );
  }, [
    effectiveFinalAnswerComing,
    state.toolGroups.length,
    state.potentialDisplayGroups,
  ]);

  // Transform toolGroups to timeline format
  const { toolTurnGroups, codeModeWorking } = useMemo(() => {
    const { steps, codeModeWorking } = expandCodeModeSteps(
      transformPacketGroups(state.toolGroups)
    );
    return { toolTurnGroups: groupStepsByTurn(steps), codeModeWorking };
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
    codeModeWorking,
    citations: state.citations,
    citationMap: state.citationMap,
    documentMap: state.documentMap,

    // Status (derived from packets)
    stopPacketSeen: state.stopPacketSeen,
    stopReason: state.stopReason,
    acceptedPacketCount: state.acceptedPacketCount,
    generatedImages: state.generatedImages,
    finalAnswerComing: state.finalAnswerComing,
    toolProcessingDuration: state.toolProcessingDuration,

    // Completion: the stream stopped, and the answer finished rendering or
    // there is no answer to render
    isComplete:
      state.stopPacketSeen &&
      (renderComplete ||
        displayGroups.length === 0 ||
        displayGroups.at(-1)?.packets[0]?.obj.type === PacketType.USER_MESSAGE),

    // Callbacks
    onRenderComplete,
    markAllToolsDisplayed,
  };
}
