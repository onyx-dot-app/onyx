// Grouping reducer + derived timeline data for one assistant message.
//
// Restructured from web (which mutates a state ref during render): mobile's react-hooks/refs lint
// forbids that, so processPackets runs as a full useMemo recompute per flush — O(n)/flush, fine at
// chat scale, re-optimizable to incremental later behind the same API. renderComplete/forceShowAnswer
// are the only true UI state; everything else derives from the packets.

import { useCallback, useMemo, useState } from "react";

import {
  CitationMap,
  SearchDoc,
  StreamingCitation,
} from "@/chat/contracts/documents";
import {
  GroupedPacket,
  ProcessedMessageState,
  createInitialState,
  processPackets,
} from "@/chat/messageProcessor";
import { GeneratedImage, Packet, StopReason } from "@/chat/streamingModels";
import {
  TurnGroup,
  expandCodeModeSteps,
  groupStepsByTurn,
  transformPacketGroups,
} from "@/chat/timeline/transformers";

export interface UsePacketProcessorResult {
  // The raw reducer output, exposed because `selectSources` and the full-text reader want the whole
  // state; deriving it in a second hook would reduce every packet twice per flush.
  processed: ProcessedMessageState;
  toolGroups: GroupedPacket[];
  displayGroups: GroupedPacket[];
  toolTurnGroups: TurnGroup[];
  /** A code mode program works between tool calls; it has no step. */
  codeModeWorking: boolean;
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, SearchDoc>;

  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;
  hasSteps: boolean;
  generatedImages: GeneratedImage[];
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

  // Reset transient UI state synchronously during render (React re-renders before commit) so a
  // message switch or a retracted answer can't briefly show the prior node's completion.
  const [prevNodeId, setPrevNodeId] = useState(nodeId);
  const [prevFinalAnswerComing, setPrevFinalAnswerComing] = useState(
    state.finalAnswerComing,
  );
  if (prevNodeId !== nodeId) {
    setPrevNodeId(nodeId);
    setPrevFinalAnswerComing(state.finalAnswerComing);
    setRenderComplete(false);
    setForceShowAnswer(false);
  } else if (prevFinalAnswerComing !== state.finalAnswerComing) {
    setPrevFinalAnswerComing(state.finalAnswerComing);
    // Tool-after-message: answer retracted, so the renderer must re-run — clear completion.
    if (prevFinalAnswerComing && !state.finalAnswerComing) {
      setRenderComplete(false);
    }
  }

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

  const { toolTurnGroups, codeModeWorking } = useMemo(() => {
    const { steps, codeModeWorking } = expandCodeModeSteps(
      transformPacketGroups(state.toolGroups),
    );
    return { toolTurnGroups: groupStepsByTurn(steps), codeModeWorking };
  }, [state.toolGroups]);

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
    processed: state,
    toolGroups: state.toolGroups,
    displayGroups,
    toolTurnGroups,
    codeModeWorking,
    citations: state.citations,
    citationMap: state.citationMap,
    documentMap: state.documentMap,

    stopPacketSeen: state.stopPacketSeen,
    stopReason: state.stopReason,
    hasSteps: toolTurnGroups.length > 0,
    generatedImages: state.generatedImages,
    finalAnswerComing: state.finalAnswerComing,
    toolProcessingDuration: state.toolProcessingDuration,

    // The stream stopped, and the answer finished rendering or there is no answer to render.
    isComplete:
      state.stopPacketSeen && (renderComplete || displayGroups.length === 0),

    onRenderComplete,
    markAllToolsDisplayed,
  };
}
