// Port of web `timeline/AgentTimeline.tsx`. Divergences: web's `headerIsInteractive` is gone, since
// it only drove a hover class and each header owns its own press target here; `useTimelineStepState`
// goes uncalled, because its only web consumers are that flag and the memory tag, which lands with
// the memory renderer; `streamingStartTime` is a prop, since mobile stamps it per assistant node
// rather than once per session; and the expanded body has no entrance animation.
import { memo, useMemo } from "react";
import { View } from "react-native";

import type { StopReason } from "@/chat/streamingModels";
import {
  isSearchToolPackets,
  stepHasCollapsedStreamingContent,
  stepSupportsCollapsedStreaming,
} from "@/chat/timeline/packetHelpers";
import type { TurnGroup } from "@/chat/timeline/transformers";
import { AgentAvatar } from "@/components/avatars/AgentAvatar";
import {
  RenderType,
  type FullChatState,
} from "@/components/chat/renderers/timelineContract";
import { CollapsedStreamingContent } from "@/components/chat/timeline/CollapsedStreamingContent";
import { ExpandedTimelineContent } from "@/components/chat/timeline/ExpandedTimelineContent";
import { CompletedHeader } from "@/components/chat/timeline/headers/CompletedHeader";
import { ParallelStreamingHeader } from "@/components/chat/timeline/headers/ParallelStreamingHeader";
import { StoppedHeader } from "@/components/chat/timeline/headers/StoppedHeader";
import { StreamingHeader } from "@/components/chat/timeline/headers/StreamingHeader";
import { ShimmerText } from "@/components/chat/timeline/ShimmerText";
import { timelineTokens } from "@/components/chat/timeline/primitives/timelineTokens";
import { TimelineHeaderRow } from "@/components/chat/timeline/primitives/TimelineHeaderRow";
import { TimelineRoot } from "@/components/chat/timeline/primitives/TimelineRoot";
import { useTimelineExpansion } from "@/hooks/timeline/useTimelineExpansion";
import { useTimelineHeader } from "@/hooks/timeline/useTimelineHeader";
import { useTimelineMetrics } from "@/hooks/timeline/useTimelineMetrics";
import {
  TimelineUIState,
  useTimelineUIState,
} from "@/hooks/timeline/useTimelineUIState";
import { cn } from "@/lib/utils";

const AVATAR_SIZE = 24;

export interface AgentTimelineProps {
  turnGroups: TurnGroup[];
  chatState: FullChatState;
  stopPacketSeen?: boolean;
  stopReason?: StopReason;
  // Gates the trailing connector and the Done step.
  finalAnswerComing?: boolean;
  hasDisplayContent?: boolean;
  collapsible?: boolean;
  buttonTitle?: string;
  // Backend duration for a hydrated (already finished) turn.
  processingDurationSeconds?: number;
  isGeneratingImage?: boolean;
  generatedImageCount?: number;
  // Backend `pre_answer_processing_seconds`; freezes the live timer once present.
  toolProcessingDuration?: number;
  // Epoch ms this node's stream started. Absent on history, where the timer falls back to the
  // backend duration.
  streamingStartTime?: number;
}

function TimelineContainer({
  agent,
  headerContent,
  children,
}: {
  agent: FullChatState["agent"];
  headerContent?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <TimelineRoot>
      <TimelineHeaderRow
        left={agent ? <AgentAvatar agent={agent} size={AVATAR_SIZE} /> : null}
      >
        {headerContent}
      </TimelineHeaderRow>
      {children}
    </TimelineRoot>
  );
}

function areAgentTimelinePropsEqual(
  prev: AgentTimelineProps,
  next: AgentTimelineProps,
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
    prev.toolProcessingDuration === next.toolProcessingDuration &&
    prev.streamingStartTime === next.streamingStartTime
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
  buttonTitle,
  processingDurationSeconds,
  isGeneratingImage = false,
  generatedImageCount = 0,
  toolProcessingDuration,
  streamingStartTime,
}: AgentTimelineProps) {
  const { headerText, hasPackets, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason,
    isGeneratingImage,
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

  const lastStepIsSearchTool = useMemo(
    () => (lastStep ? isSearchToolPackets(lastStep.packets) : false),
    [lastStep],
  );

  const { isExpanded, handleToggle, parallelActiveTab, setParallelActiveTab } =
    useTimelineExpansion(stopPacketSeen, lastTurnGroup, hasDisplayContent);

  const parallelActiveStep = useMemo(() => {
    if (!lastTurnGroup?.isParallel) return undefined;
    return (
      lastTurnGroup.steps.find((step) => step.key === parallelActiveTab) ??
      lastTurnGroup.steps[0]
    );
  }, [lastTurnGroup, parallelActiveTab]);

  const parallelActiveStepSupportsCollapsedStreaming = useMemo(
    () =>
      parallelActiveStep
        ? stepSupportsCollapsedStreaming(parallelActiveStep.packets)
        : false,
    [parallelActiveStep],
  );

  const lastStepHasCollapsedContent = useMemo(
    () =>
      lastStep ? stepHasCollapsedStreamingContent(lastStep.packets) : false,
    [lastStep],
  );

  const parallelActiveStepHasCollapsedContent = useMemo(
    () =>
      parallelActiveStep
        ? stepHasCollapsedStreamingContent(parallelActiveStep.packets)
        : false,
    [parallelActiveStep],
  );

  // A cancelled run only counts the steps that actually produced something.
  const stoppedStepsCount = useMemo(() => {
    if (!stopPacketSeen || !userStopped) return totalSteps;
    let count = 0;
    for (const turnGroup of turnGroups) {
      for (const step of turnGroup.steps) {
        if (stepHasCollapsedStreamingContent(step.packets)) count += 1;
      }
    }
    return count;
  }, [stopPacketSeen, userStopped, totalSteps, turnGroups]);

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
    ],
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

  const collapsedRenderTypeOverride = useMemo(() => {
    if (lastStepIsResearchAgent) return RenderType.HIGHLIGHT;
    if (lastStepIsCodingAgent) return RenderType.HIGHLIGHT;
    if (lastStepIsSearchTool) return RenderType.INLINE;
    return RenderType.COMPACT;
  }, [lastStepIsResearchAgent, lastStepIsCodingAgent, lastStepIsSearchTool]);

  if (uiState === TimelineUIState.EMPTY) {
    return (
      <TimelineContainer
        agent={chatState.agent}
        headerContent={
          <View
            className="h-full w-full flex-row items-center"
            style={{
              paddingLeft: timelineTokens.headerPaddingLeft,
              paddingRight: timelineTokens.headerPaddingRight,
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

  // Expanded, a parallel turn reads as a sequential run, so it drops back to the normal header.
  const showParallelHeader = showParallelTabs && lastTurnGroup !== undefined;
  const isStreamingState =
    uiState === TimelineUIState.STREAMING_PARALLEL ||
    uiState === TimelineUIState.STREAMING_SEQUENTIAL;

  let header: React.ReactNode = null;
  if (isStreamingState && showParallelHeader) {
    header = (
      <ParallelStreamingHeader
        steps={lastTurnGroup.steps}
        activeTab={parallelActiveTab}
        onTabChange={setParallelActiveTab}
        collapsible={collapsible}
        isExpanded={isExpanded}
        onToggle={handleToggle}
      />
    );
  } else if (isStreamingState) {
    header = (
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
  } else if (uiState === TimelineUIState.STOPPED) {
    header = (
      <StoppedHeader
        totalSteps={stoppedStepsCount}
        collapsible={collapsible}
        isExpanded={isExpanded}
        onToggle={handleToggle}
      />
    );
  } else {
    header = (
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
  }

  return (
    <TimelineContainer
      agent={chatState.agent}
      headerContent={
        <View
          className={cn(
            "h-full min-w-0 flex-1 flex-row items-center justify-between rounded-t-12 p-4",
            showTintedBackground && "bg-background-tint-00",
            showRoundedBottom && "rounded-b-12",
          )}
        >
          {header}
        </View>
      }
    >
      {showCollapsedCompact && lastStep ? (
        <CollapsedStreamingContent
          step={lastStep}
          chatState={chatState}
          stopReason={stopReason}
          renderTypeOverride={collapsedRenderTypeOverride}
        />
      ) : null}

      {showCollapsedParallel && parallelActiveStep ? (
        <CollapsedStreamingContent
          step={parallelActiveStep}
          chatState={chatState}
          stopReason={stopReason}
          renderTypeOverride={RenderType.HIGHLIGHT}
        />
      ) : null}

      {isExpanded ? (
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
      ) : null}
    </TimelineContainer>
  );
}, areAgentTimelinePropsEqual);

export default AgentTimeline;
