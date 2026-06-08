// useTimelineUIState.ts — pure timeline UI state machine.
//
// Mirrors web useTimelineUIState.

import { useMemo } from "react";
import { TurnGroup, TransformedStep } from "@/state/timeline/transformers";

export enum TimelineUIState {
  EMPTY = "EMPTY",
  DISPLAY_CONTENT_ONLY = "DISPLAY_CONTENT_ONLY",
  STREAMING_SEQUENTIAL = "STREAMING_SEQUENTIAL",
  STREAMING_PARALLEL = "STREAMING_PARALLEL",
  STOPPED = "STOPPED",
  COMPLETED_COLLAPSED = "COMPLETED_COLLAPSED",
  COMPLETED_EXPANDED = "COMPLETED_EXPANDED",
}

export interface TimelineUIStateInput {
  stopPacketSeen: boolean;
  hasPackets: boolean;
  hasDisplayContent: boolean;
  userStopped: boolean;
  isExpanded: boolean;
  lastTurnGroup: TurnGroup | undefined;
  lastStep: TransformedStep | undefined;
  lastStepSupportsCollapsedStreaming: boolean;
  lastStepHasCollapsedContent: boolean;
  lastStepIsResearchAgent: boolean;
  parallelActiveStepSupportsCollapsedStreaming: boolean;
  parallelActiveStepHasCollapsedContent: boolean;
  isGeneratingImage: boolean;
  finalAnswerComing: boolean;
}

export interface TimelineUIStateResult {
  uiState: TimelineUIState;
  isStreaming: boolean;
  isCompleted: boolean;
  isActivelyExecuting: boolean;
  showCollapsedCompact: boolean;
  showCollapsedParallel: boolean;
  showParallelTabs: boolean;
  showDoneStep: boolean;
  showStoppedStep: boolean;
  hasDoneIndicator: boolean;
  showTintedBackground: boolean;
  showRoundedBottom: boolean;
}

export function useTimelineUIState(
  input: TimelineUIStateInput
): TimelineUIStateResult {
  return useMemo(() => {
    const {
      stopPacketSeen,
      hasPackets,
      hasDisplayContent,
      userStopped,
      isExpanded,
      lastTurnGroup,
      lastStep,
      lastStepSupportsCollapsedStreaming,
      lastStepHasCollapsedContent,
      lastStepIsResearchAgent,
      parallelActiveStepSupportsCollapsedStreaming,
      parallelActiveStepHasCollapsedContent,
      isGeneratingImage,
      finalAnswerComing,
    } = input;

    let uiState: TimelineUIState;

    if (!hasPackets && !hasDisplayContent && !stopPacketSeen) {
      uiState = TimelineUIState.EMPTY;
    } else if (hasDisplayContent && !hasPackets && !isGeneratingImage) {
      uiState = TimelineUIState.DISPLAY_CONTENT_ONLY;
    } else if (!stopPacketSeen && (!hasDisplayContent || isGeneratingImage)) {
      uiState = lastTurnGroup?.isParallel
        ? TimelineUIState.STREAMING_PARALLEL
        : TimelineUIState.STREAMING_SEQUENTIAL;
    } else if (userStopped) {
      uiState = TimelineUIState.STOPPED;
    } else if (isExpanded) {
      uiState = TimelineUIState.COMPLETED_EXPANDED;
    } else {
      uiState = TimelineUIState.COMPLETED_COLLAPSED;
    }

    const isStreaming =
      uiState === TimelineUIState.STREAMING_SEQUENTIAL ||
      uiState === TimelineUIState.STREAMING_PARALLEL;
    const isCompleted =
      uiState === TimelineUIState.COMPLETED_COLLAPSED ||
      uiState === TimelineUIState.COMPLETED_EXPANDED ||
      uiState === TimelineUIState.STOPPED;
    const isActivelyExecuting =
      !stopPacketSeen && (!hasDisplayContent || isGeneratingImage);

    const showParallelTabs =
      uiState === TimelineUIState.STREAMING_PARALLEL &&
      !isExpanded &&
      !!lastTurnGroup?.isParallel &&
      (lastTurnGroup?.steps.length ?? 0) > 0;

    const showCollapsedCompact =
      uiState === TimelineUIState.STREAMING_SEQUENTIAL &&
      !isExpanded &&
      !!lastStep &&
      !lastTurnGroup?.isParallel &&
      lastStepSupportsCollapsedStreaming &&
      lastStepHasCollapsedContent;

    const showCollapsedParallel =
      showParallelTabs &&
      !isExpanded &&
      parallelActiveStepSupportsCollapsedStreaming &&
      parallelActiveStepHasCollapsedContent;

    const showDoneStep =
      (stopPacketSeen || finalAnswerComing) &&
      isExpanded &&
      (!userStopped || hasDisplayContent);

    const showStoppedStep =
      stopPacketSeen && isExpanded && userStopped && !hasDisplayContent;

    const hasDoneIndicator =
      (stopPacketSeen || finalAnswerComing) &&
      isExpanded &&
      !userStopped &&
      !lastStepIsResearchAgent;

    const showTintedBackground = isActivelyExecuting || isExpanded;
    const showRoundedBottom =
      !isExpanded && !showCollapsedCompact && !showCollapsedParallel;

    return {
      uiState,
      isStreaming,
      isCompleted,
      isActivelyExecuting,
      showCollapsedCompact,
      showCollapsedParallel,
      showParallelTabs,
      showDoneStep,
      showStoppedStep,
      hasDoneIndicator,
      showTintedBackground,
      showRoundedBottom,
    };
  }, [input]);
}
