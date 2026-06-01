/* eslint-disable react-hooks/refs, react-hooks/purity -- streamingStartRef is a
   render-stable timer origin captured once; reading it during render is
   intentional and matches the web AgentTimeline. */
// Native mirror of web AgentTimeline.

import { memo, useMemo, useRef, type ReactNode } from "react";
import { View } from "react-native";
import Animated, { FadeIn } from "react-native-reanimated";

import type { StopReason } from "@/lib/types";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { RenderType, type FullChatState } from "@/components/message/interfaces";
import { useTimelineHeader } from "@/state/timeline/hooks/useTimelineHeader";
import { useTimelineMetrics } from "@/state/timeline/hooks/useTimelineMetrics";
import { useTimelineExpansion } from "@/state/timeline/hooks/useTimelineExpansion";
import { useTimelineStepState } from "@/state/timeline/hooks/useTimelineStepState";
import {
  useTimelineUIState,
  TimelineUIState,
} from "@/state/timeline/hooks/useTimelineUIState";
import {
  isSearchToolPackets,
  stepSupportsCollapsedStreaming,
  stepHasCollapsedStreamingContent,
} from "@/state/timeline/packetHelpers";
import type { TurnGroup } from "@/state/timeline/transformers";
import { ShimmerText } from "@/components/message/timeline/primitives/ShimmerText";
import { TimelineRoot } from "@/components/message/timeline/primitives/TimelineRoot";
import { TimelineHeaderRow } from "@/components/message/timeline/primitives/TimelineHeaderRow";
import { AgentAvatar } from "@/components/message/AgentAvatar";
import { StreamingHeader } from "@/components/message/timeline/headers/StreamingHeader";
import { CompletedHeader } from "@/components/message/timeline/headers/CompletedHeader";
import { StoppedHeader } from "@/components/message/timeline/headers/StoppedHeader";
import { ParallelStreamingHeader } from "@/components/message/timeline/headers/ParallelStreamingHeader";
import { CollapsedStreamingContent } from "@/components/message/timeline/CollapsedStreamingContent";
import { ExpandedTimelineContent } from "@/components/message/timeline/ExpandedTimelineContent";
import { timelineTokens as T } from "@/theme/timelineTokens";

export interface AgentTimelineProps {
  turnGroups: TurnGroup[];
  chatState: FullChatState;
  stopPacketSeen?: boolean;
  stopReason?: StopReason;
  finalAnswerComing?: boolean;
  hasDisplayContent?: boolean;
  collapsible?: boolean;
  processingDurationSeconds?: number;
  isGeneratingImage?: boolean;
  generatedImageCount?: number;
  toolProcessingDuration?: number;
}

function areEqual(prev: AgentTimelineProps, next: AgentTimelineProps): boolean {
  return (
    prev.turnGroups === next.turnGroups &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.finalAnswerComing === next.finalAnswerComing &&
    prev.hasDisplayContent === next.hasDisplayContent &&
    prev.processingDurationSeconds === next.processingDurationSeconds &&
    prev.collapsible === next.collapsible &&
    prev.chatState === next.chatState &&
    prev.isGeneratingImage === next.isGeneratingImage &&
    prev.generatedImageCount === next.generatedImageCount &&
    prev.toolProcessingDuration === next.toolProcessingDuration
  );
}

function TimelineContainer({
  agent,
  headerContent,
  children,
}: {
  agent: FullChatState["agent"];
  headerContent?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <TimelineRoot>
      <TimelineHeaderRow left={<AgentAvatar agent={agent} size={24} />}>
        {headerContent}
      </TimelineHeaderRow>
      {children}
    </TimelineRoot>
  );
}

export const AgentTimeline = memo(function AgentTimeline({
  turnGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  finalAnswerComing = false,
  hasDisplayContent = false,
  collapsible = true,
  processingDurationSeconds,
  isGeneratingImage = false,
  generatedImageCount = 0,
  toolProcessingDuration,
}: AgentTimelineProps) {
  const colors = useThemeColors();
  const streamingStartRef = useRef<number>(Date.now());

  const { headerText, hasPackets, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason,
    isGeneratingImage
  );

  const {
    totalSteps,
    isSingleStep,
    lastTurnGroup,
    lastStep,
    lastStepIsResearchAgent,
    lastStepIsCodingAgent,
    lastStepSupportsCollapsedStreaming,
  } = useTimelineMetrics(turnGroups, userStopped);

  const { memoryText, memoryOperation, isMemoryOnly } =
    useTimelineStepState(turnGroups);

  const lastStepIsSearchTool = useMemo(
    () => (lastStep ? isSearchToolPackets(lastStep.packets) : false),
    [lastStep]
  );

  const { isExpanded, handleToggle, parallelActiveTab, setParallelActiveTab } =
    useTimelineExpansion(stopPacketSeen, lastTurnGroup, hasDisplayContent);

  const parallelActiveStep = useMemo(() => {
    if (!lastTurnGroup?.isParallel) return null;
    return (
      lastTurnGroup.steps.find((s) => s.key === parallelActiveTab) ??
      lastTurnGroup.steps[0] ??
      null
    );
  }, [lastTurnGroup, parallelActiveTab]);

  const parallelActiveStepSupportsCollapsedStreaming = useMemo(
    () =>
      parallelActiveStep
        ? stepSupportsCollapsedStreaming(parallelActiveStep.packets)
        : false,
    [parallelActiveStep]
  );
  const lastStepHasCollapsedContent = useMemo(
    () => (lastStep ? stepHasCollapsedStreamingContent(lastStep.packets) : false),
    [lastStep]
  );
  const parallelActiveStepHasCollapsedContent = useMemo(
    () =>
      parallelActiveStep
        ? stepHasCollapsedStreamingContent(parallelActiveStep.packets)
        : false,
    [parallelActiveStep]
  );

  const uiStateInput = useMemo(
    () => ({
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
    }),
    [
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
    ]
  );

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
  } = useTimelineUIState(uiStateInput);

  const stoppedStepsCount = useMemo(() => {
    if (!stopPacketSeen || !userStopped) return totalSteps;
    let count = 0;
    for (const tg of turnGroups) {
      for (const step of tg.steps) {
        if (stepHasCollapsedStreamingContent(step.packets)) count += 1;
      }
    }
    return count;
  }, [stopPacketSeen, userStopped, totalSteps, turnGroups]);

  const collapsedRenderTypeOverride = useMemo(() => {
    if (lastStepIsResearchAgent) return RenderType.HIGHLIGHT;
    if (lastStepIsCodingAgent) return RenderType.HIGHLIGHT;
    if (lastStepIsSearchTool) return RenderType.INLINE;
    return RenderType.COMPACT;
  }, [lastStepIsResearchAgent, lastStepIsCodingAgent, lastStepIsSearchTool]);

  function renderHeader(): ReactNode {
    switch (uiState) {
      case TimelineUIState.STREAMING_PARALLEL:
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
      // falls through to sequential when expanded / no group
      case TimelineUIState.STREAMING_SEQUENTIAL:
        return (
          <StreamingHeader
            headerText={headerText}
            collapsible={collapsible}
            isExpanded={isExpanded}
            onToggle={handleToggle}
            streamingStartTime={streamingStartRef.current}
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
          />
        );
      default:
        return null;
    }
  }

  // Empty state: no packets, still streaming.
  if (uiState === TimelineUIState.EMPTY) {
    return (
      <TimelineContainer
        agent={chatState.agent}
        headerContent={
          <View
            style={{
              flex: 1,
              height: "100%",
              flexDirection: "row",
              alignItems: "center",
              paddingLeft: T.headerPaddingLeft,
              paddingRight: T.headerPaddingRight,
            }}
          >
            <ShimmerText>{headerText}</ShimmerText>
          </View>
        }
      />
    );
  }

  if (uiState === TimelineUIState.DISPLAY_CONTENT_ONLY) {
    return <TimelineContainer agent={chatState.agent} />;
  }

  return (
    <TimelineContainer
      agent={chatState.agent}
      headerContent={
        <View
          style={[
            {
              flex: 1,
              minWidth: 0,
              height: "100%",
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              padding: 4,
              borderTopLeftRadius: radii["12"],
              borderTopRightRadius: radii["12"],
            },
            showTintedBackground
              ? { backgroundColor: colors["background-tint-00"] }
              : null,
            showRoundedBottom
              ? {
                  borderBottomLeftRadius: radii["12"],
                  borderBottomRightRadius: radii["12"],
                }
              : null,
          ]}
        >
          {renderHeader()}
        </View>
      }
    >
      {showCollapsedCompact && lastStep && (
        <CollapsedStreamingContent
          step={lastStep}
          chatState={chatState}
          stopReason={stopReason}
          renderTypeOverride={collapsedRenderTypeOverride}
        />
      )}

      {showCollapsedParallel && parallelActiveStep && (
        <CollapsedStreamingContent
          step={parallelActiveStep}
          chatState={chatState}
          stopReason={stopReason}
          renderTypeOverride={RenderType.HIGHLIGHT}
        />
      )}

      {isExpanded && (
        <Animated.View entering={FadeIn.duration(300)}>
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
        </Animated.View>
      )}
    </TimelineContainer>
  );
}, areEqual);

export default AgentTimeline;
