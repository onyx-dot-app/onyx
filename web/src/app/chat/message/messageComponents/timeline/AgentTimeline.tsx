"use client";

import React, { FunctionComponent, useMemo, useCallback } from "react";
import { StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState } from "../interfaces";
import { TurnGroup, TransformedStep } from "./transformers";
import { cn } from "@/lib/utils";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgCheckCircle, SvgStopCircle } from "@opal/icons";
import { IconProps } from "@opal/types";
import {
  TimelineRendererComponent,
  TimelineRendererResult,
} from "./TimelineRendererComponent";
import Text from "@/refresh-components/texts/Text";
import { ParallelTimelineTabs } from "./ParallelTimelineTabs";
import { StepContainer } from "./StepContainer";
import {
  useTimelineExpansion,
  useTimelineMetrics,
  useTimelineHeader,
} from "@/app/chat/message/messageComponents/timeline/hooks";
import {
  isResearchAgentPackets,
  stepSupportsCompact,
} from "@/app/chat/message/messageComponents/timeline/packetHelpers";
import {
  StreamingHeader,
  CollapsedHeader,
  ExpandedHeader,
  StoppedHeader,
  ParallelStreamingHeader,
} from "@/app/chat/message/messageComponents/timeline/headers";

// =============================================================================
// TimelineStep Component - Memoized to prevent re-renders
// =============================================================================

interface TimelineStepProps {
  step: TransformedStep;
  chatState: FullChatState;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  isLastStep: boolean;
  isFirstStep: boolean;
  isSingleStep: boolean;
}

//will be removed on cleanup
const noopCallback = () => {};

const TimelineStep = React.memo(function TimelineStep({
  step,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastStep,
  isFirstStep,
  isSingleStep,
}: TimelineStepProps) {
  // Stable render callback - doesn't need to change between renders
  const renderStep = useCallback(
    ({
      icon,
      status,
      content,
      isExpanded,
      onToggle,
      isLastStep: rendererIsLastStep,
      supportsCompact,
    }: TimelineRendererResult) =>
      isResearchAgentPackets(step.packets) ? (
        content
      ) : (
        <StepContainer
          stepIcon={icon as FunctionComponent<IconProps> | undefined}
          header={status}
          isExpanded={isExpanded}
          onToggle={onToggle}
          collapsible={true}
          supportsCompact={supportsCompact}
          isLastStep={rendererIsLastStep}
          isFirstStep={isFirstStep}
          hideHeader={isSingleStep}
        >
          {content}
        </StepContainer>
      ),
    [step.packets, isFirstStep, isSingleStep]
  );

  return (
    <TimelineRendererComponent
      packets={step.packets}
      chatState={chatState}
      onComplete={noopCallback}
      animate={!stopPacketSeen}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
      defaultExpanded={true}
      isLastStep={isLastStep}
    >
      {renderStep}
    </TimelineRendererComponent>
  );
});

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
  /** Additional class names */
  className?: string;
  /** Test ID for e2e testing */
  "data-testid"?: string;
  /** Unique tool names (pre-computed for performance) */
  uniqueToolNames?: string[];
}

export function AgentTimeline({
  turnGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  finalAnswerComing = false,
  hasDisplayContent = false,
  collapsible = true,
  buttonTitle,
  className,
  "data-testid": testId,
  uniqueToolNames = [],
}: AgentTimelineProps) {
  // Header text and state flags
  const { headerText, hasPackets, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason
  );

  // Memoized metrics derived from turn groups
  const {
    totalSteps,
    isSingleStep,
    uniqueTools,
    lastTurnGroup,
    lastStep,
    lastStepIsResearchAgent,
    lastStepSupportsCompact,
  } = useTimelineMetrics(turnGroups, uniqueToolNames, userStopped);

  // Expansion state management
  const { isExpanded, handleToggle, parallelActiveTab, setParallelActiveTab } =
    useTimelineExpansion(stopPacketSeen, lastTurnGroup);

  // Stable callbacks to avoid creating new functions on every render
  const noopComplete = useCallback(() => {}, []);
  const renderContentOnly = useCallback(
    ({ content }: TimelineRendererResult) => content,
    []
  );

  // Parallel step analysis for collapsed streaming view
  const parallelActiveStep = useMemo(() => {
    if (!lastTurnGroup?.isParallel) return null;
    return (
      lastTurnGroup.steps.find((s) => s.key === parallelActiveTab) ??
      lastTurnGroup.steps[0]
    );
  }, [lastTurnGroup, parallelActiveTab]);

  const parallelActiveStepSupportsCompact = useMemo(() => {
    if (!parallelActiveStep) return false;
    return (
      stepSupportsCompact(parallelActiveStep.packets) &&
      !isResearchAgentPackets(parallelActiveStep.packets)
    );
  }, [parallelActiveStep]);

  // Collapsed streaming: show compact content below header
  const showCollapsedCompact =
    !stopPacketSeen &&
    !isExpanded &&
    lastStep &&
    !lastTurnGroup?.isParallel &&
    !lastStepIsResearchAgent &&
    lastStepSupportsCompact;

  // Parallel tabs in header only when collapsed (expanded view has tabs in content)
  const showParallelTabs =
    !stopPacketSeen &&
    !isExpanded &&
    lastTurnGroup?.isParallel &&
    lastTurnGroup.steps.length > 0;

  // Collapsed parallel compact content
  const showCollapsedParallel =
    showParallelTabs && !isExpanded && parallelActiveStepSupportsCompact;

  // Done indicator conditions
  const showDoneIndicator =
    stopPacketSeen && isExpanded && !userStopped && !lastStepIsResearchAgent;

  // Header selection based on state
  const renderHeader = () => {
    if (!stopPacketSeen) {
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
      return (
        <StreamingHeader
          headerText={headerText}
          collapsible={collapsible}
          buttonTitle={buttonTitle}
          isExpanded={isExpanded}
          onToggle={handleToggle}
        />
      );
    }

    if (userStopped) {
      return (
        <StoppedHeader
          totalSteps={totalSteps}
          collapsible={collapsible}
          isExpanded={isExpanded}
          onToggle={handleToggle}
        />
      );
    }

    if (!isExpanded) {
      return (
        <CollapsedHeader
          uniqueTools={uniqueTools}
          totalSteps={totalSteps}
          collapsible={collapsible}
          onToggle={handleToggle}
        />
      );
    }

    return <ExpandedHeader collapsible={collapsible} onToggle={handleToggle} />;
  };

  // Empty state: no packets, still streaming
  if (!hasPackets && !hasDisplayContent) {
    return (
      <div className={cn("flex flex-col", className)}>
        <div className="flex w-full h-9">
          <div className="flex justify-center items-center size-9">
            <AgentAvatar agent={chatState.assistant} size={24} />
          </div>
          <div className="flex w-full h-full items-center px-2">
            <Text
              as="p"
              mainUiAction
              text03
              className="animate-shimmer bg-[length:200%_100%] bg-[linear-gradient(90deg,var(--shimmer-base)_10%,var(--shimmer-highlight)_40%,var(--shimmer-base)_70%)] bg-clip-text text-transparent"
            >
              {headerText}
            </Text>
          </div>
        </div>
      </div>
    );
  }

  // Display content only (no timeline steps)
  if (hasDisplayContent && !hasPackets) {
    return (
      <div className={cn("flex flex-col", className)}>
        <div className="flex w-full h-9">
          <div className="flex justify-center items-center size-9">
            <AgentAvatar agent={chatState.assistant} size={24} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col", className)}>
      {/* Header row */}
      <div className="flex w-full h-9">
        <div className="flex justify-center items-center size-9">
          <AgentAvatar agent={chatState.assistant} size={24} />
        </div>
        <div
          className={cn(
            "flex w-full h-full items-center justify-between px-2",
            (!stopPacketSeen || userStopped || isExpanded) &&
              "bg-background-tint-00 rounded-t-12",
            !isExpanded &&
              !showCollapsedCompact &&
              !showCollapsedParallel &&
              "rounded-b-12"
          )}
        >
          {renderHeader()}
        </div>
      </div>

      {/* Collapsed streaming view - single step compact mode */}
      {showCollapsedCompact && lastStep && (
        <div className="flex w-full">
          <div className="w-9" />
          <div className="w-full bg-background-tint-00 rounded-b-12 px-2 pb-2">
            <TimelineRendererComponent
              key={`${lastStep.key}-compact`}
              packets={lastStep.packets}
              chatState={chatState}
              onComplete={noopComplete}
              animate={true}
              stopPacketSeen={false}
              stopReason={stopReason}
              defaultExpanded={false}
              isLastStep={true}
            >
              {renderContentOnly}
            </TimelineRendererComponent>
          </div>
        </div>
      )}

      {/* Collapsed streaming view - parallel tools compact mode */}
      {showCollapsedParallel && parallelActiveStep && (
        <div className="flex w-full">
          <div className="w-9" />
          <div className="w-full bg-background-tint-00 rounded-b-12 px-2 pb-2">
            <TimelineRendererComponent
              key={`${parallelActiveStep.key}-compact`}
              packets={parallelActiveStep.packets}
              chatState={chatState}
              onComplete={noopComplete}
              animate={true}
              stopPacketSeen={false}
              stopReason={stopReason}
              defaultExpanded={false}
              isLastStep={true}
            >
              {renderContentOnly}
            </TimelineRendererComponent>
          </div>
        </div>
      )}

      {/* Expanded timeline view */}
      {isExpanded && (
        <div className="w-full">
          {turnGroups.map((turnGroup, turnIdx) =>
            turnGroup.isParallel ? (
              <ParallelTimelineTabs
                key={turnGroup.turnIndex}
                turnGroup={turnGroup}
                chatState={chatState}
                stopPacketSeen={stopPacketSeen}
                stopReason={stopReason}
                isLastTurnGroup={turnIdx === turnGroups.length - 1}
              />
            ) : (
              turnGroup.steps.map((step, stepIdx) => {
                const stepIsLast =
                  turnIdx === turnGroups.length - 1 &&
                  stepIdx === turnGroup.steps.length - 1 &&
                  !showDoneIndicator &&
                  !userStopped;
                const stepIsFirst = turnIdx === 0 && stepIdx === 0;

                return (
                  <TimelineStep
                    key={step.key}
                    step={step}
                    chatState={chatState}
                    stopPacketSeen={stopPacketSeen}
                    stopReason={stopReason}
                    isLastStep={stepIsLast}
                    isFirstStep={stepIsFirst}
                    isSingleStep={isSingleStep}
                  />
                );
              })
            )
          )}

          {/* Done indicator */}
          {stopPacketSeen && isExpanded && !userStopped && (
            <StepContainer
              stepIcon={SvgCheckCircle}
              header="Done"
              isLastStep={true}
              isFirstStep={false}
            >
              {null}
            </StepContainer>
          )}

          {/* Stopped indicator */}
          {stopPacketSeen && isExpanded && userStopped && (
            <StepContainer
              stepIcon={SvgStopCircle}
              header="Stopped"
              isLastStep={true}
              isFirstStep={false}
            >
              {null}
            </StepContainer>
          )}
        </div>
      )}
    </div>
  );
}

export default AgentTimeline;
