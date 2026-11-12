import { useMemo } from "react";
import { TransformedStep } from "../transformers";

// =============================================================================
// Timeline UI State Machine
// =============================================================================

export enum TimelineUIState {
  /** No packets yet, showing shimmer */
  EMPTY = "EMPTY",
  /** Final message only, no timeline */
  DISPLAY_CONTENT_ONLY = "DISPLAY_CONTENT_ONLY",
  /** Tools are running */
  STREAMING = "STREAMING",
  /** User cancelled */
  STOPPED = "STOPPED",
  /** Done, timeline collapsed */
  COMPLETED_COLLAPSED = "COMPLETED_COLLAPSED",
  /** Done, timeline expanded */
  COMPLETED_EXPANDED = "COMPLETED_EXPANDED",
}

export interface TimelineUIStateInput {
  /** Whether the stop packet has been seen */
  stopPacketSeen: boolean;
  /** Whether there are any packets in the timeline */
  hasPackets: boolean;
  /** Whether there is display content after timeline */
  hasDisplayContent: boolean;
  /** Whether the user stopped the generation */
  userStopped: boolean;
  /** Whether the timeline is expanded */
  isExpanded: boolean;
  /** The last step */
  lastStep: TransformedStep | undefined;
  /** Whether the last step supports collapsed streaming rendering */
  lastStepSupportsCollapsedStreaming: boolean;
  /** Whether the last step has renderable collapsed streaming content */
  lastStepHasCollapsedContent: boolean;
  /** Whether the last step is a research agent */
  lastStepIsResearchAgent: boolean;
  /** Whether final answer is coming (MESSAGE_START received) */
  finalAnswerComing: boolean;
}

export interface TimelineUIStateResult {
  /** The current UI state */
  uiState: TimelineUIState;

  // Convenience booleans
  /** Whether actively streaming (tool execution in progress) */
  isStreaming: boolean;
  /** Whether completed (stop packet seen) */
  isCompleted: boolean;
  /** Whether actively executing tools (streaming without display content) */
  isActivelyExecuting: boolean;

  // Display flags
  /** Show collapsed compact content for single step */
  showCollapsedCompact: boolean;
  /** Show the "Done" indicator step in expanded view */
  showDoneStep: boolean;
  /** Show the "Stopped" indicator step in expanded view */
  showStoppedStep: boolean;
  /** For stepIsLast calculation (excludes research agent) */
  hasDoneIndicator: boolean;

  // Styling flags
  /** Show tinted background on header */
  showTintedBackground: boolean;
  /** Show rounded bottom on header */
  showRoundedBottom: boolean;
}

/**
 * Derives the current UI state from timeline inputs.
 * Centralizes all boolean logic for timeline rendering decisions.
 */
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
      lastStep,
      lastStepSupportsCollapsedStreaming,
      lastStepHasCollapsedContent,
      lastStepIsResearchAgent,
      finalAnswerComing,
    } = input;

    // Derive the primary UI state
    let uiState: TimelineUIState;

    if (!hasPackets && !hasDisplayContent && !stopPacketSeen) {
      uiState = TimelineUIState.EMPTY;
    } else if (hasDisplayContent && !hasPackets) {
      uiState = TimelineUIState.DISPLAY_CONTENT_ONLY;
    } else if (!stopPacketSeen && !hasDisplayContent) {
      // Actively executing tools
      uiState = TimelineUIState.STREAMING;
    } else if (userStopped) {
      uiState = TimelineUIState.STOPPED;
    } else if (isExpanded) {
      uiState = TimelineUIState.COMPLETED_EXPANDED;
    } else {
      uiState = TimelineUIState.COMPLETED_COLLAPSED;
    }

    // Convenience booleans
    const isStreaming = uiState === TimelineUIState.STREAMING;
    const isCompleted =
      uiState === TimelineUIState.COMPLETED_COLLAPSED ||
      uiState === TimelineUIState.COMPLETED_EXPANDED ||
      uiState === TimelineUIState.STOPPED;
    const isActivelyExecuting = !stopPacketSeen && !hasDisplayContent;

    // Collapsed streaming: show compact content below header (only during tool execution)
    const showCollapsedCompact =
      uiState === TimelineUIState.STREAMING &&
      !isExpanded &&
      !!lastStep &&
      lastStepSupportsCollapsedStreaming &&
      lastStepHasCollapsedContent;

    // Done step: shown when expanded and completed (either normally or with display content)
    // Also shown when finalAnswerComing is true (MESSAGE_START received)
    const showDoneStep =
      (stopPacketSeen || finalAnswerComing) &&
      isExpanded &&
      (!userStopped || hasDisplayContent);

    // Stopped step: shown when user stopped without display content
    const showStoppedStep =
      stopPacketSeen && isExpanded && userStopped && !hasDisplayContent;

    // For stepIsLast calculation: done indicator present (excludes research agent)
    const hasDoneIndicator =
      (stopPacketSeen || finalAnswerComing) &&
      isExpanded &&
      !userStopped &&
      !lastStepIsResearchAgent;

    // Styling flags
    const showTintedBackground = isActivelyExecuting || isExpanded;
    const showRoundedBottom = !isExpanded && !showCollapsedCompact;

    return {
      uiState,
      isStreaming,
      isCompleted,
      isActivelyExecuting,
      showCollapsedCompact,
      showDoneStep,
      showStoppedStep,
      hasDoneIndicator,
      showTintedBackground,
      showRoundedBottom,
    };
  }, [input]);
}
