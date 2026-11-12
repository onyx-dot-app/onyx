"use client";

import React, { useMemo, useCallback } from "react";
import { StopReason } from "@/app/app/services/streamingModels";
import {
  FullChatState,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { TurnGroup } from "./transformers";
import { cn } from "@opal/utils";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { TextLoader } from "@opal/loaders";
import { useTimelineExpansion } from "@/lib/timeline/chat/hooks/useTimelineExpansion";
import { useTimelineMetrics } from "@/lib/timeline/chat/hooks/useTimelineMetrics";
import { useTimelineHeader } from "@/lib/timeline/chat/hooks/useTimelineHeader";
import {
  useTimelineUIState,
  TimelineUIState,
} from "@/lib/timeline/chat/hooks/useTimelineUIState";
import {
  isResearchAgentPackets,
  isSearchToolPackets,
  stepHasCollapsedStreamingContent,
} from "@/lib/timeline/chat/packetHelpers";
import { useTimelineStepState } from "@/lib/timeline/chat/hooks/useTimelineStepState";
import { StreamingHeader } from "@/lib/timeline/chat/headers/StreamingHeader";
import { CompletedHeader } from "@/lib/timeline/chat/headers/CompletedHeader";
import { StoppedHeader } from "@/lib/timeline/chat/headers/StoppedHeader";
import { useStreamingStartTime } from "@/app/app/stores/useChatSessionStore";
import { ExpandedTimelineContent } from "./ExpandedTimelineContent";
import { CollapsedStreamingContent } from "./CollapsedStreamingContent";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { TimelineHeaderRow } from "@/lib/timeline/components/primitives/TimelineHeaderRow";

// =============================================================================
// Private Wrapper Components
// =============================================================================

interface TimelineContainerProps {
  agent: FullChatState["agent"];
  headerContent?: React.ReactNode;
  children?: React.ReactNode;
}

function TimelineContainer({
  agent,
  headerContent,
  children,
}: TimelineContainerProps) {
  return (
    <TimelineRoot>
      <TimelineHeaderRow left={<AgentAvatar agent={agent} size={24} />}>
        {headerContent}
      </TimelineHeaderRow>
      {children}
    </TimelineRoot>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export interface AgentTimelineProps {
  /** Turn groups from usePacketProcessor */
  turnGroups: TurnGroup[];
  /** Chat state for rendering content */
  chatState: FullChatState;
  /** Whether the stop packet has been seen */
  stopPacketSeen?: boolean;
  /** Reason for stopping (if stopped) */
  stopReason?: StopReason;
  /** Whether final answer is coming (affects last connector) */
  finalAnswerComing?: boolean;
  /** Whether there is display content after timeline */
  hasDisplayContent?: boolean;
  /** Content to render after timeline (final message + toolbar) - slot pattern */
  children?: React.ReactNode;
  /** Whether the timeline is collapsible */
  collapsible?: boolean;
  /** Title of the button to toggle the timeline */
  buttonTitle?: string;
  /** Test ID for e2e testing */
  "data-testid"?: string;
  /** Processing duration in seconds (for completed messages) */
  processingDurationSeconds?: number;
  /** Number of images generated */
  generatedImageCount?: number;
  /** Tool processing duration from backend (via MESSAGE_START packet) */
  toolProcessingDuration?: number;
  /** A code mode program works between tool calls; it has no step */
  codeModeWorking?: boolean;
}

/**
 * Custom prop comparison for AgentTimeline memoization.
 * Prevents unnecessary re-renders when parent renders but props haven't meaningfully changed.
 */
function areAgentTimelinePropsEqual(
  prev: AgentTimelineProps,
  next: AgentTimelineProps
): boolean {
  return (
    prev.turnGroups === next.turnGroups &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.finalAnswerComing === next.finalAnswerComing &&
    prev.hasDisplayContent === next.hasDisplayContent &&
    prev.processingDurationSeconds === next.processingDurationSeconds &&
    prev.collapsible === next.collapsible &&
    prev.buttonTitle === next.buttonTitle &&
    prev.chatState === next.chatState &&
    prev.generatedImageCount === next.generatedImageCount &&
    prev.toolProcessingDuration === next.toolProcessingDuration &&
    prev.codeModeWorking === next.codeModeWorking
  );
}

export const AgentTimeline = React.memo(function AgentTimeline({
  turnGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  finalAnswerComing = false,
  hasDisplayContent = false,
  collapsible = true,
  buttonTitle,
  "data-testid": testId,
  processingDurationSeconds,
  generatedImageCount = 0,
  toolProcessingDuration,
  codeModeWorking = false,
}: AgentTimelineProps) {
  // Header text and state flags
  const { headerText, hasPackets, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason,
    codeModeWorking
  );

  // Memoized metrics derived from turn groups
  const {
    totalSteps,
    isSingleStep,
    lastStep,
    lastStepIsResearchAgent,
    lastStepIsCodingAgent,
    lastStepSupportsCollapsedStreaming,
  } = useTimelineMetrics(turnGroups, userStopped);

  // Extract memory text, operation, and whether this is a memory-only timeline
  const { memoryText, memoryOperation, memoryId, memoryIndex, isMemoryOnly } =
    useTimelineStepState(turnGroups);

  // Check if last step is a search tool for INLINE render type
  const lastStepIsSearchTool = useMemo(
    () => lastStep && isSearchToolPackets(lastStep.packets),
    [lastStep]
  );

  const { isExpanded, handleToggle } = useTimelineExpansion(
    stopPacketSeen,
    hasDisplayContent
  );

  // Streaming duration tracking
  const streamingStartTime = useStreamingStartTime();

  const lastStepHasCollapsedContent = useMemo(() => {
    if (!lastStep) return false;
    return stepHasCollapsedStreamingContent(lastStep.packets);
  }, [lastStep]);

  const stoppedStepsCount = useMemo(() => {
    if (!stopPacketSeen || !userStopped) {
      return totalSteps;
    }

    let count = 0;
    for (const turnGroup of turnGroups) {
      for (const step of turnGroup.steps) {
        if (stepHasCollapsedStreamingContent(step.packets)) {
          count += 1;
        }
      }
    }

    return count;
  }, [stopPacketSeen, userStopped, totalSteps, turnGroups]);

  // Derive all UI state from inputs
  const {
    uiState,
    showCollapsedCompact,
    showDoneStep,
    showStoppedStep,
    hasDoneIndicator,
    showTintedBackground,
    showRoundedBottom,
  } = useTimelineUIState({
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
  });

  const headerIsInteractive = useMemo(() => {
    if (!collapsible || isMemoryOnly) {
      return false;
    }

    if (uiState === TimelineUIState.STOPPED) {
      return stoppedStepsCount > 0;
    }

    return totalSteps > 0;
  }, [collapsible, isMemoryOnly, uiState, stoppedStepsCount, totalSteps]);

  // Determine render type override for collapsed streaming view
  const collapsedRenderTypeOverride = useMemo(() => {
    if (lastStepIsResearchAgent) return RenderType.HIGHLIGHT;
    if (lastStepIsCodingAgent) return RenderType.HIGHLIGHT;
    if (lastStepIsSearchTool) return RenderType.INLINE;
    return RenderType.COMPACT;
  }, [lastStepIsResearchAgent, lastStepIsCodingAgent, lastStepIsSearchTool]);

  // Header selection based on UI state
  const renderHeader = useCallback(() => {
    switch (uiState) {
      case TimelineUIState.STREAMING:
        return (
          <StreamingHeader
            headerText={headerText}
            collapsible={collapsible}
            buttonTitle={buttonTitle}
            isExpanded={isExpanded}
            onToggle={handleToggle}
            streamingStartTime={streamingStartTime}
            toolProcessingDuration={toolProcessingDuration}
          />
        );

      case TimelineUIState.STOPPED:
        return (
          <StoppedHeader
            totalSteps={stoppedStepsCount}
            collapsible={collapsible}
            isExpanded={isExpanded}
            onToggle={handleToggle}
          />
        );

      case TimelineUIState.COMPLETED_COLLAPSED:
      case TimelineUIState.COMPLETED_EXPANDED:
        return (
          <CompletedHeader
            totalSteps={totalSteps}
            collapsible={collapsible}
            isExpanded={isExpanded}
            onToggle={handleToggle}
            processingDurationSeconds={
              toolProcessingDuration ?? processingDurationSeconds
            }
            generatedImageCount={generatedImageCount}
            isMemoryOnly={isMemoryOnly}
            memoryText={memoryText}
            memoryOperation={memoryOperation}
            memoryId={memoryId}
            memoryIndex={memoryIndex}
          />
        );

      default:
        return null;
    }
  }, [
    uiState,
    collapsible,
    isExpanded,
    handleToggle,
    headerText,
    buttonTitle,
    streamingStartTime,
    isMemoryOnly,
    memoryText,
    memoryOperation,
    memoryId,
    memoryIndex,
    totalSteps,
    stoppedStepsCount,
    processingDurationSeconds,
    generatedImageCount,
    toolProcessingDuration,
  ]);

  // Empty state: no packets, still streaming, and not stopped
  if (uiState === TimelineUIState.EMPTY) {
    return (
      <TimelineContainer
        agent={chatState.agent}
        headerContent={
          <div className="flex w-full h-full items-center ps-(--timeline-header-padding-left) pe-(--timeline-header-padding-right)">
            <TextLoader>{headerText}</TextLoader>
          </div>
        }
      />
    );
  }

  // Display content only (no timeline steps)
  if (uiState === TimelineUIState.DISPLAY_CONTENT_ONLY) {
    return <TimelineContainer agent={chatState.agent} />;
  }

  return (
    <TimelineContainer
      agent={chatState.agent}
      headerContent={
        <div
          className={cn(
            "flex flex-1 min-w-0 h-full items-center justify-between p-1 rounded-t-12 transition-colors duration-300",
            headerIsInteractive && "hover:bg-background-tint-00",
            showTintedBackground && "bg-background-tint-00",
            showRoundedBottom && "rounded-b-12"
          )}
        >
          {renderHeader()}
        </div>
      }
    >
      {/* Collapsed streaming view - single step compact mode */}
      {showCollapsedCompact && lastStep && (
        <CollapsedStreamingContent
          step={lastStep}
          chatState={chatState}
          stopReason={stopReason}
          renderTypeOverride={collapsedRenderTypeOverride}
        />
      )}

      {/* Expanded timeline view */}
      {isExpanded && (
        <div className="animate-in fade-in slide-in-from-top-2 duration-300">
          <ExpandedTimelineContent
            turnGroups={turnGroups}
            chatState={chatState}
            stopPacketSeen={stopPacketSeen}
            stopReason={stopReason}
            isSingleStep={isSingleStep}
            userStopped={userStopped}
            showDoneStep={showDoneStep}
            showStoppedStep={showStoppedStep}
            hasDoneIndicator={hasDoneIndicator}
          />
        </div>
      )}
    </TimelineContainer>
  );
}, areAgentTimelinePropsEqual);

export default AgentTimeline;
