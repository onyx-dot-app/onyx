"use client";

import React, { FunctionComponent, useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import {
  TurnGroup,
  TransformedStep,
  toChatTimelineGroup,
} from "@/lib/timeline/chat/transformers";
import { SvgCheckCircle, SvgStopCircle } from "@opal/icons";
import { IconProps } from "@opal/types";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
  TimelineRendererResult,
} from "@/lib/timeline/chat/TimelineRendererComponent";
import { StepContainer } from "@/lib/timeline/components/StepContainer";
import { TimelineSteps } from "@/lib/timeline/components/TimelineSteps";
import { TimelineStepComposer } from "@/lib/timeline/chat/TimelineStepComposer";
import {
  isSearchToolPackets,
  isPythonToolPackets,
} from "@/lib/timeline/chat/packetHelpers";

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
    () => isSearchToolPackets(step.packets),
    [step.packets]
  );
  const isPythonTool = useMemo(
    () => isPythonToolPackets(step.packets),
    [step.packets]
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
      packets={step.packets}
      nestedCalls={step.nestedCalls}
      streamPackets={step.streamPackets}
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
    const groups = useMemo(
      () => turnGroups.map(toChatTimelineGroup),
      [turnGroups]
    );

    return (
      <div className="w-full">
        <TimelineSteps
          groups={groups}
          renderEntry={(entry, position) => (
            <TimelineStep
              step={entry.payload}
              chatState={chatState}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
              isLastStep={position.isLast && !hasDoneIndicator && !userStopped}
              isFirstStep={position.isFirst}
              isSingleStep={isSingleStep}
              isStreaming={!stopPacketSeen && !userStopped}
            />
          )}
        />

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
