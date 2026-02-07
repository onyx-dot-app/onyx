"use client";

import React, { useMemo, useCallback } from "react";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState, RenderType } from "../interfaces";
import { TurnGroup } from "./transformers";
import { cn } from "@/lib/utils";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Text from "@/refresh-components/texts/Text";
import { useTimelineExpansion } from "@/app/app/message/messageComponents/timeline/hooks/useTimelineExpansion";
import { useTimelineMetrics } from "@/app/app/message/messageComponents/timeline/hooks/useTimelineMetrics";
import { useTimelineHeader } from "@/app/app/message/messageComponents/timeline/hooks/useTimelineHeader";
import {
  useTimelineUIState,
  TimelineUIState,
} from "@/app/app/message/messageComponents/timeline/hooks/useTimelineUIState";
import {
  isResearchAgentPackets,
  isSearchToolPackets,
  stepSupportsCollapsedStreaming,
  stepHasCollapsedStreamingContent,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";
import { StreamingHeader } from "@/app/app/message/messageComponents/timeline/headers/StreamingHeader";
import { CompletedHeader } from "@/app/app/message/messageComponents/timeline/headers/CompletedHeader";
import { StoppedHeader } from "@/app/app/message/messageComponents/timeline/headers/StoppedHeader";
import { ParallelStreamingHeader } from "@/app/app/message/messageComponents/timeline/headers/ParallelStreamingHeader";
import { useStreamingStartTime } from "@/app/app/stores/useChatSessionStore";
import { ExpandedTimelineContent } from "./ExpandedTimelineContent";
import { CollapsedStreamingContent } from "./CollapsedStreamingContent";
import { TimelineRoot } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRoot";
import { TimelineHeaderRow } from "@/app/app/message/messageComponents/timeline/primitives/TimelineHeaderRow";

// =============================================================================
// Private Wrapper Components
// =============================================================================

interface TimelineContainerProps {
  agent: FullChatState["assistant"];
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
  /** Whether image generation is in progress */
  isGeneratingImage?: boolean;
  /** Number of images generated */
  generatedImageCount?: number;
  /** Tool processing duration from backend (via MESSAGE_START packet) */
  toolProcessingDuration?: number;
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
    prev.isGeneratingImage === next.isGeneratingImage &&
    prev.generatedImageCount === next.generatedImageCount &&
    prev.toolProcessingDuration === next.toolProcessingDuration
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
  isGeneratingImage = false,
  generatedImageCount = 0,
  toolProcessingDuration,
}: AgentTimelineProps) {
  // Header text and state flags
  const { headerText, hasPackets, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason,
    isGeneratingImage
  );

  // Memoized metrics derived from turn groups
  const {
    totalSteps,
    isSingleStep,
    lastTurnGroup,
    lastStep,
    lastStepIsResearchAgent,
    lastStepSupportsCollapsedStreaming,
  } = useTimelineMetrics(turnGroups, userStopped);

  // Check if last step is a search tool for INLINE render type
  const lastStepIsSearchTool = useMemo(
    () => lastStep && isSearchToolPackets(lastStep.packets),
    [lastStep]
  );

  const { isExpanded, handleToggle, parallelActiveTab, setParallelActiveTab } =
    useTimelineExpansion(stopPacketSeen, lastTurnGroup, hasDisplayContent);

  // Streaming duration tracking
  const streamingStartTime = useStreamingStartTime();

  // Parallel step analysis for collapsed streaming view
  const parallelActiveStep = useMemo(() => {
    if (!lastTurnGroup?.isParallel) return null;
    return (
      lastTurnGroup.steps.find((s) => s.key === parallelActiveTab) ??
      lastTurnGroup.steps[0]
    );
  }, [lastTurnGroup, parallelActiveTab]);

  const parallelActiveStepSupportsCollapsedStreaming = useMemo(() => {
    if (!parallelActiveStep) return false;
    return stepSupportsCollapsedStreaming(parallelActiveStep.packets);
  }, [parallelActiveStep]);

  const lastStepHasCollapsedContent = useMemo(() => {
    if (!lastStep) return false;
    return stepHasCollapsedStreamingContent(lastStep.packets);
  }, [lastStep]);

  const parallelActiveStepHasCollapsedContent = useMemo(() => {
    if (!parallelActiveStep) return false;
    return stepHasCollapsedStreamingContent(parallelActiveStep.packets);
  }, [parallelActiveStep]);

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
    showCollapsedParallel,
    showParallelTabs,
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
    lastTurnGroup,
    lastStep,
    lastStepSupportsCollapsedStreaming,
    lastStepHasCollapsedContent,
    lastStepIsResearchAgent,
    parallelActiveStepSupportsCollapsedStreaming,
    parallelActiveStepHasCollapsedContent,
    isGeneratingImage,
    finalAnswerComing,
  });

  const headerIsInteractive = useMemo(() => {
    if (!collapsible) {
      return false;
    }

    if (uiState === TimelineUIState.STOPPED) {
      return stoppedStepsCount > 0;
    }

    return totalSteps > 0;
  }, [collapsible, uiState, stoppedStepsCount, totalSteps]);

  // Determine render type override for collapsed streaming view
  const collapsedRenderTypeOverride = useMemo(() => {
    if (lastStepIsResearchAgent) return RenderType.HIGHLIGHT;
    if (lastStepIsSearchTool) return RenderType.INLINE;
    return RenderType.COMPACT;
  }, [lastStepIsResearchAgent, lastStepIsSearchTool]);

  // Header selection based on UI state
  const renderHeader = useCallback(() => {
    switch (uiState) {
      case TimelineUIState.STREAMING_PARALLEL:
        // Only show parallel header when collapsed (showParallelTabs includes !isExpanded check)
        if (showParallelTabs && lastTurnGroup) {
          return (
            <ParallelStreamingHeader
              steps={lastTurnGroup.steps}
              activeTab={parallelActiveTab}
              onTabChange={setParallelActiveTab}
              collapsible={collapsible}
              isExpanded={isExpanded}
              onToggle={handleToggle}
            />
          );
        }
      // falls through to sequential header when expanded or no lastTurnGroup
      case TimelineUIState.STREAMING_SEQUENTIAL:
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
          />
        );

      default:
        return null;
    }
  }, [
    uiState,
    showParallelTabs,
    lastTurnGroup,
    parallelActiveTab,
    setParallelActiveTab,
    collapsible,
    isExpanded,
    handleToggle,
    headerText,
    buttonTitle,
    streamingStartTime,
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
        agent={chatState.assistant}
        headerContent={
          <div className="flex w-full h-full items-center pl-[var(--timeline-header-padding-left)] pr-[var(--timeline-header-padding-right)]">
            <Text
              as="p"
              mainUiAction
              text03
              className="animate-shimmer bg-[length:200%_100%] bg-[linear-gradient(90deg,var(--shimmer-base)_10%,var(--shimmer-highlight)_40%,var(--shimmer-base)_70%)] bg-clip-text text-transparent"
            >
              {headerText}
            </Text>
          </div>
        }
      />
    );
  }

  // Display content only (no timeline steps) - but show header for image generation
  if (uiState === TimelineUIState.DISPLAY_CONTENT_ONLY) {
    return <TimelineContainer agent={chatState.assistant} />;
  }

  return (
    <TimelineContainer
      agent={chatState.assistant}
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

      {/* Collapsed streaming view - parallel tools compact mode */}
      {showCollapsedParallel && parallelActiveStep && (
        <CollapsedStreamingContent
          step={parallelActiveStep}
          chatState={chatState}
          stopReason={stopReason}
          renderTypeOverride={RenderType.HIGHLIGHT}
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
