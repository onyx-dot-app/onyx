"use client";

import React, { FunctionComponent, useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import {
  TurnGroup,
  TransformedStep,
} from "@/app/app/message/messageComponents/timeline/transformers";
import { SvgCheckCircle, SvgStopCircle } from "@opal/icons";
import { IconProps } from "@opal/types";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
  TimelineRendererResult,
} from "@/app/app/message/messageComponents/timeline/TimelineRendererComponent";
import { ParallelTimelineTabs } from "@/app/app/message/messageComponents/timeline/ParallelTimelineTabs";
import { StepContainer } from "@/app/app/message/messageComponents/timeline/StepContainer";
import { TimelineStepComposer } from "@/app/app/message/messageComponents/timeline/TimelineStepComposer";
import {
  isCodingAgentItems,
  isPythonToolItems,
  isSearchToolItems,
} from "@/app/app/message/messageComponents/timeline/itemHelpers";

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
  const isSearchTool = useMemo(
    () => isSearchToolItems(step.items),
    [step.items]
  );
  const isPythonTool = useMemo(
    () => isPythonToolItems(step.items),
    [step.items]
  );
  const getCollapsedIcon = useCallback(
    (result: TimelineRendererResult) =>
      isSearchTool ? (result.icon as FunctionComponent<IconProps>) : undefined,
    [isSearchTool]
  );

  const renderStep = useCallback(
    (results: TimelineRendererOutput) => (
      <TimelineStepComposer
        results={results}
        isLastStep={isLastStep}
        isFirstStep={isFirstStep}
        isSingleStep={isSingleStep}
        collapsible={true}
        getCollapsedIcon={getCollapsedIcon}
      />
    ),
    [isFirstStep, isLastStep, isSingleStep, getCollapsedIcon]
  );

  return (
    <TimelineRendererComponent
      items={step.items}
      chatState={chatState}
      animate={!stopPacketSeen}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
      defaultExpanded={isStreaming || (isSingleStep && !isPythonTool)}
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
    const t = useTranslations("chat.messages.timeline");

    return (
      <div className="w-full">
        {turnGroups.map((turnGroup, turnIdx) => {
          // Coding-agent groups always render via ParallelTimelineTabs so
          // their tab-pill chrome is consistent with the multi-agent case.
          const renderAsParallelTabs =
            turnGroup.isParallel ||
            turnGroup.steps.some((step) => isCodingAgentItems(step.items));

          return renderAsParallelTabs ? (
            <ParallelTimelineTabs
              key={turnGroup.turnIndex}
              turnGroup={turnGroup}
              chatState={chatState}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
              isLastTurnGroup={
                turnIdx === turnGroups.length - 1 &&
                !showDoneStep &&
                !showStoppedStep
              }
              isFirstTurnGroup={turnIdx === 0}
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
          );
        })}

        {/* Done indicator */}
        {showDoneStep && (
          <StepContainer
            stepIcon={SvgCheckCircle}
            header={t("doneStep.header")}
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
            header={t("stoppedStep.header")}
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
