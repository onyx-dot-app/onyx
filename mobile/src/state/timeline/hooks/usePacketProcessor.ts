/* eslint-disable react-hooks/refs -- Intentional incremental ref-processor:
   ProcessorState is held in a ref and read/reset during render (a legal
   derived-from-props reset) to process packets synchronously with no extra
   render. Ported verbatim from the battle-tested web usePacketProcessor. */
// usePacketProcessor.ts — React wrapper around the incremental packetProcessor.
//
// Mirrors web usePacketProcessor.
// ProcessorState lives in a ref (synchronous incremental processing, no double
// render). Only renderComplete/forceShowAnswer are useState. Resets on nodeId
// change / stream shrink happen during render (legal derived-from-props reset).
//
// NOTE (mobile): rawPackets is a NEW array reference each store flush (mobile's
// applyPacket clones); the index-based cursor is identity-agnostic so this is
// safe. Keep `rawPackets.length` (not reference) as the change signal.

import { useRef, useState, useMemo, useCallback } from "react";
import {
  Packet,
  StreamingCitation,
  StopReason,
  OnyxDocument,
  CitationMap,
} from "@/lib/types";
import {
  ProcessorState,
  GroupedPacket,
  createInitialState,
  processPackets,
} from "@/state/timeline/packetProcessor";
import {
  transformPacketGroups,
  groupStepsByTurn,
  TurnGroup,
} from "@/state/timeline/transformers";

export interface UsePacketProcessorResult {
  toolGroups: GroupedPacket[];
  displayGroups: GroupedPacket[];
  toolTurnGroups: TurnGroup[];
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, OnyxDocument>;

  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;
  hasSteps: boolean;
  expectedBranchesPerTurn: Map<number, number>;
  isGeneratingImage: boolean;
  generatedImageCount: number;
  finalAnswerComing: boolean;
  toolProcessingDuration: number | undefined;

  isComplete: boolean;

  onRenderComplete: () => void;
  markAllToolsDisplayed: () => void;
}

export function usePacketProcessor(
  rawPackets: Packet[],
  nodeId: number
): UsePacketProcessorResult {
  const stateRef = useRef<ProcessorState>(createInitialState(nodeId));

  const [renderComplete, setRenderComplete] = useState(false);
  const [forceShowAnswer, setForceShowAnswer] = useState(false);

  // Reset on nodeId change
  if (stateRef.current.nodeId !== nodeId) {
    stateRef.current = createInitialState(nodeId);
    setRenderComplete(false);
    setForceShowAnswer(false);
  }

  const prevNextPacketIndex = stateRef.current.nextPacketIndex;
  const prevFinalAnswerComing = stateRef.current.finalAnswerComing;

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

  // Reset renderComplete on tool-after-message transition
  if (prevFinalAnswerComing && !stateRef.current.finalAnswerComing) {
    setRenderComplete(false);
  }

  const state = stateRef.current;

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

  const toolTurnGroups = useMemo(() => {
    const allSteps = transformPacketGroups(state.toolGroups);
    return groupStepsByTurn(allSteps);
  }, [state.toolGroups]);

  const onRenderComplete = useCallback(() => {
    if (stateRef.current.finalAnswerComing) {
      setRenderComplete(true);
    }
  }, []);

  const markAllToolsDisplayed = useCallback(() => {
    setForceShowAnswer(true);
  }, []);

  return {
    toolGroups: state.toolGroups,
    displayGroups,
    toolTurnGroups,
    citations: state.citations,
    citationMap: state.citationMap,
    documentMap: state.documentMap,

    stopPacketSeen: state.stopPacketSeen,
    stopReason: state.stopReason,
    hasSteps: toolTurnGroups.length > 0,
    expectedBranchesPerTurn: state.expectedBranches,
    isGeneratingImage: state.isGeneratingImage,
    generatedImageCount: state.generatedImageCount,
    finalAnswerComing: state.finalAnswerComing,
    toolProcessingDuration: state.toolProcessingDuration,

    isComplete: state.stopPacketSeen && renderComplete,

    onRenderComplete,
    markAllToolsDisplayed,
  };
}
