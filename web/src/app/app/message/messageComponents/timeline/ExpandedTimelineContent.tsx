"use client";

import React, { FunctionComponent, useMemo, useCallback } from "react";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState } from "../interfaces";
import { TurnGroup, TransformedStep } from "./transformers";
import { SvgCheckCircle, SvgStopCircle } from "@opal/icons";
import { IconProps } from "@opal/types";
import {
  TimelineRendererComponent,
  TimelineRendererResult,
  TimelineRendererOutput,
} from "./TimelineRendererComponent";
import { ParallelTimelineTabs } from "./ParallelTimelineTabs";
import { StepContainer } from "./StepContainer";
import {
  isResearchAgentPackets,
  isSearchToolPackets,
  isReasoningPackets,
  isDeepResearchPlanPackets,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";

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
  isStreaming?: boolean;
}

const noopCallback = () => {};

const TimelineStep = React.memo(function TimelineStep({
  step,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastStep,
  isFirstStep,
  isSingleStep,
  isStreaming = false,
}: TimelineStepProps) {
  const isResearchAgent = useMemo(
    () => isResearchAgentPackets(step.packets),
    [step.packets]
  );
  const isSearchTool = useMemo(
    () => isSearchToolPackets(step.packets),
    [step.packets]
  );
  const isReasoning = useMemo(
    () => isReasoningPackets(step.packets),
    [step.packets]
  );
  const isDeepResearchPlan = useMemo(
    () => isDeepResearchPlanPackets(step.packets),
    [step.packets]
  );

  const renderStep = useCallback(
    (results: TimelineRendererOutput) => {
      if (isResearchAgent) {
        return (
          <>
            {results.map((result, index) => (
              <React.Fragment key={index}>{result.content}</React.Fragment>
            ))}
          </>
        );
      }

      return (
        <>
          {results.map((result, index) => (
            <StepContainer
              key={index}
              stepIcon={result.icon as FunctionComponent<IconProps> | undefined}
              header={result.status}
              isExpanded={result.isExpanded}
              onToggle={result.onToggle}
              collapsible={true}
              supportsCollapsible={result.supportsCollapsible}
              isLastStep={index === results.length - 1 && isLastStep}
              isFirstStep={index === 0 && isFirstStep}
              hideHeader={results.length === 1 && isSingleStep}
              collapsedIcon={
                isSearchTool
                  ? (result.icon as FunctionComponent<IconProps>)
                  : undefined
              }
              noPaddingRight={isReasoning || isDeepResearchPlan}
            >
              {result.content}
            </StepContainer>
          ))}
        </>
      );
    },
    [
      isResearchAgent,
      isSearchTool,
      isReasoning,
      isDeepResearchPlan,
      isFirstStep,
      isLastStep,
      isSingleStep,
    ]
  );

  return (
    <TimelineRendererComponent
      packets={step.packets}
      chatState={chatState}
      onComplete={noopCallback}
      animate={!stopPacketSeen}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
      defaultExpanded={isStreaming || isSingleStep}
      isLastStep={isLastStep}
    >
      {renderStep}
    </TimelineRendererComponent>
  );
});

// =============================================================================
// ExpandedTimelineContent Component
// =============================================================================

export interface ExpandedTimelineContentProps {
  turnGroups: TurnGroup[];
  chatState: FullChatState;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  isSingleStep: boolean;
  userStopped: boolean;
  showDoneStep: boolean;
  showStoppedStep: boolean;
  hasDoneIndicator: boolean;
}

export const ExpandedTimelineContent = React.memo(
  function ExpandedTimelineContent({
    turnGroups,
    chatState,
    stopPacketSeen,
    stopReason,
    isSingleStep,
    userStopped,
    showDoneStep,
    showStoppedStep,
    hasDoneIndicator,
  }: ExpandedTimelineContentProps) {
    return (
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
                !hasDoneIndicator &&
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
                  isStreaming={!stopPacketSeen && !userStopped}
                />
              );
            })
          )
        )}

        {/* Done indicator */}
        {showDoneStep && (
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
        {showStoppedStep && (
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
    );
  }
);

export default ExpandedTimelineContent;
