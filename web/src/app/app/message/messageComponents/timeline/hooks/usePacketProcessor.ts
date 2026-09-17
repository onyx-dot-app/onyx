/* oxlint-disable react-doctor/no-ref-current-in-render -- render-phase
   incremental processing is the core design: the packet cursor makes
   replays idempotent and consumers need the state in the same commit. */
import { useRef, useState, useMemo, useCallback } from "react";
import {
  Packet,
  StreamingCitation,
  StopReason,
} from "@/app/app/services/streamingModels";
import { CitationMap } from "@/app/app/interfaces";
import { OnyxDocument } from "@/lib/search/types";
import {
  ProcessorState,
  createInitialState,
  processPackets,
  GroupedItem,
} from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import {
  transformItemGroups,
  groupStepsByTurn,
  TurnGroup,
} from "@/app/app/message/messageComponents/timeline/transformers";

export interface UsePacketProcessorResult {
  // Data
  toolGroups: GroupedItem[];
  narrationGroups: GroupedItem[];
  displayGroups: GroupedItem[];
  toolTurnGroups: TurnGroup[];
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, OnyxDocument>;

  // Status (derived from packets)
  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;
  hasSteps: boolean;

  isGeneratingImage: boolean;
  generatedImageCount: number;
  // Whether final answer is coming (an answer item exists)
  finalAnswerComing: boolean;
  // Tool processing duration from backend (from the answer item)
  toolProcessingDuration: number | undefined;

  // Completion: stopPacketSeen && renderComplete
  isComplete: boolean;

  // Callbacks
  onRenderComplete: () => void;
  markAllToolsDisplayed: () => void;
}

/** Keep stream state separate from animation and answer-visibility state. */
export function usePacketProcessor(
  rawPackets: Packet[],
  nodeId: number
): UsePacketProcessorResult {
  // Processor in ref: incremental, synchronous, no double render
  const stateRef = useRef<ProcessorState>(createInitialState(nodeId));
  const lastProcessedPacketRef = useRef<Packet | undefined>(undefined);

  const [renderComplete, setRenderComplete] = useState(false);

  // Optional override to force showing answer
  const [forceShowAnswer, setForceShowAnswer] = useState(false);

  // Resume replaces saved history; its packet offsets belong to a different sequence.
  const nextPacketIndex = stateRef.current.nextPacketIndex;
  if (
    stateRef.current.nodeId !== nodeId ||
    (nextPacketIndex > 0 &&
      rawPackets[nextPacketIndex - 1] !== lastProcessedPacketRef.current)
  ) {
    stateRef.current = createInitialState(nodeId);
    lastProcessedPacketRef.current = undefined;
    setRenderComplete(false);
    setForceShowAnswer(false);
  }

  // Track for transition detection
  const prevFinalAnswerComing = stateRef.current.finalAnswerComing;

  // Process packets synchronously (incremental) - only if new packets arrived
  if (rawPackets.length > stateRef.current.nextPacketIndex) {
    stateRef.current = processPackets(stateRef.current, rawPackets);
    lastProcessedPacketRef.current = rawPackets[rawPackets.length - 1];
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
    const allSteps = transformItemGroups(state.toolGroups);
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
    narrationGroups: state.narrationGroups,
    displayGroups,
    toolTurnGroups,
    citations: state.citations,
    citationMap: state.citationMap,
    documentMap: state.documentMap,

    // Status (derived from packets)
    stopPacketSeen: state.stopPacketSeen,
    stopReason: state.stopReason,
    hasSteps: toolTurnGroups.length > 0,
    isGeneratingImage: state.isGeneratingImage,
    generatedImageCount: state.generatedImageCount,
    finalAnswerComing: state.finalAnswerComing,
    toolProcessingDuration: state.toolProcessingDuration,

    // Completion: stopPacketSeen && renderComplete
    isComplete: state.stopPacketSeen && renderComplete,

    // Callbacks
    onRenderComplete,
    markAllToolsDisplayed,
  };
}
