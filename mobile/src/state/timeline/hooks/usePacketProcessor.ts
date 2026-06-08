/* eslint-disable react-hooks/refs -- Intentional incremental ref-processor:
   ProcessorState is held in a ref and read/reset during render (a legal
   derived-from-props reset) to process packets synchronously with no extra
   render. Ported verbatim from the battle-tested web usePacketProcessor. */
// Mirrors web usePacketProcessor.
// Mobile gotcha: rawPackets is a NEW array reference each store flush (applyPacket
// clones), so the index-based cursor (identity-agnostic) is the safe signal —
// gate on `rawPackets.length`, not the array reference.

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

  // Reset on nodeId change.
  if (stateRef.current.nodeId !== nodeId) {
    stateRef.current = createInitialState(nodeId);
    setRenderComplete(false);
    setForceShowAnswer(false);
  }

  const prevNextPacketIndex = stateRef.current.nextPacketIndex;
  const prevFinalAnswerComing = stateRef.current.finalAnswerComing;

  // Stream reset: packets shrunk.
  if (prevNextPacketIndex > rawPackets.length) {
    stateRef.current = createInitialState(nodeId);
    setRenderComplete(false);
    setForceShowAnswer(false);
  }

  if (rawPackets.length > stateRef.current.nextPacketIndex) {
    stateRef.current = processPackets(stateRef.current, rawPackets);
  }

  // Tool-after-message transition: replay the answer render.
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
