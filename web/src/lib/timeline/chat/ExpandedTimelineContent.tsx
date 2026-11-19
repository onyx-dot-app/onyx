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
import { STEP_ICONS } from "@/lib/timeline/icons";
import type { TimelineEntryStatus } from "@/lib/timeline/types";
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
  /** Replaces the step's icon while it runs or after it failed. */
  statusIcon?: FunctionComponent<IconProps>;
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
  statusIcon,
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
        statusIcon={statusIcon}
      />
    ),
    [isFirstStep, isLastStep, isSingleStep, getCollapsedIcon, statusIcon]
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
              statusIcon={stepStatusIcon(
                entry.status,
                stopPacketSeen,
                userStopped
              )}
            />
          )}
        />

        {/* Done indicator */}
        {showDoneStep && (
          <StepContainer
            stepIcon={STEP_ICONS.done}
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
            stepIcon={STEP_ICONS.stopped}
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

/**
 * As in Craft: a running step shows the spinner, and a failed or stopped one
 * the alert. A step without an end after a finished stream counts as done.
 */
function stepStatusIcon(
  status: TimelineEntryStatus,
  stopPacketSeen: boolean,
  userStopped: boolean
): FunctionComponent<IconProps> | undefined {
  if (status === "error") return STEP_ICONS.failed;
  if (status !== "streaming") return undefined;
  if (!stopPacketSeen) return STEP_ICONS.running;
  return userStopped ? STEP_ICONS.failed : undefined;
}
