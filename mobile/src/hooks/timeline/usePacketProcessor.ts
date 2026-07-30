// Grouping reducer + derived timeline data for one assistant message.
//
// Restructured from web (which mutates a state ref during render): mobile's react-hooks/refs lint
// forbids that, so processPackets runs as a full useMemo recompute per flush — O(n)/flush, fine at
// chat scale, re-optimizable to incremental later behind the same API. renderComplete/forceShowAnswer
// are the only true UI state; everything else derives from the packets.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  CitationMap,
  SearchDoc,
  StreamingCitation,
} from "@/chat/contracts/documents";
import {
  GroupedPacket,
  createInitialState,
  processPackets,
} from "@/chat/messageProcessor";
import { Packet, StopReason } from "@/chat/streamingModels";
import {
  TurnGroup,
  groupStepsByTurn,
  transformPacketGroups,
} from "@/chat/timeline/transformers";

export interface UsePacketProcessorResult {
  toolGroups: GroupedPacket[];
  displayGroups: GroupedPacket[];
  toolTurnGroups: TurnGroup[];
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, SearchDoc>;

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
  nodeId: number,
): UsePacketProcessorResult {
  const [renderComplete, setRenderComplete] = useState(false);
  const [forceShowAnswer, setForceShowAnswer] = useState(false);

  const state = useMemo(
    () => processPackets(createInitialState(nodeId), rawPackets),
    [nodeId, rawPackets],
  );

  // Reset transient UI state on a message switch or stream rewind — in an effect, not during render,
  // so react-hooks/refs stays satisfied.
  const prevNodeIdRef = useRef(nodeId);
  const prevFinalAnswerComingRef = useRef(state.finalAnswerComing);
  useEffect(() => {
    if (prevNodeIdRef.current !== nodeId) {
      setRenderComplete(false);
      setForceShowAnswer(false);
    } else if (prevFinalAnswerComingRef.current && !state.finalAnswerComing) {
      // Tool-after-message: answer retracted, so the renderer must re-run — clear completion.
      setRenderComplete(false);
    }
    prevNodeIdRef.current = nodeId;
    prevFinalAnswerComingRef.current = state.finalAnswerComing;
  }, [nodeId, state.finalAnswerComing]);

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

  const toolTurnGroups = useMemo(
    () => groupStepsByTurn(transformPacketGroups(state.toolGroups)),
    [state.toolGroups],
  );

  // Read the current render's finalAnswerComing, not an effect-lagged mirror — so a renderer's
  // onComplete fired in the same commit the answer begins isn't dropped.
  const onRenderComplete = useCallback(() => {
    if (state.finalAnswerComing) {
      setRenderComplete(true);
    }
  }, [state.finalAnswerComing]);

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
