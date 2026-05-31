// ExpandedTimelineContent.tsx — full step list when the timeline is expanded.
// Ported from web ExpandedTimelineContent (parallel/coding groups -> tabs;
// sequential steps -> StepContainer rows; Done/Stopped terminal rows).

import { memo, useMemo } from "react";
import { View } from "react-native";

import type { StopReason } from "@/lib/types";
import type { FullChatState } from "@/components/message/interfaces";
import type { TurnGroup, TransformedStep } from "@/state/timeline/transformers";
import {
  isPythonToolPackets,
  isCodingAgentPackets,
} from "@/state/timeline/packetHelpers";
import {
  TimelineRendererComponent,
  type TimelineRendererOutput,
} from "@/components/message/timeline/TimelineRendererComponent";
import { TimelineStepComposer } from "@/components/message/timeline/TimelineStepComposer";
import { ParallelTimelineTabs } from "@/components/message/timeline/ParallelTimelineTabs";
import { StepContainer } from "@/components/message/timeline/StepContainer";

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

const TimelineStep = memo(function TimelineStep({
  step,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastStep,
  isFirstStep,
  isSingleStep,
  isStreaming = false,
}: TimelineStepProps) {
  const isPythonTool = useMemo(
    () => isPythonToolPackets(step.packets),
    [step.packets]
  );

  const renderStep = (results: TimelineRendererOutput) => (
    <TimelineStepComposer
      results={results}
      isLastStep={isLastStep}
      isFirstStep={isFirstStep}
      isSingleStep={isSingleStep}
      collapsible
    />
  );

  return (
    <TimelineRendererComponent
      packets={step.packets}
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

export const ExpandedTimelineContent = memo(function ExpandedTimelineContent({
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
    <View style={{ width: "100%" }}>
      {turnGroups.map((turnGroup, turnIdx) => {
        const renderAsParallelTabs =
          turnGroup.isParallel ||
          turnGroup.steps.some((s) => isCodingAgentPackets(s.packets));

        if (renderAsParallelTabs) {
          return (
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
          );
        }

        return turnGroup.steps.map((step, stepIdx) => {
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
        });
      })}

      {showDoneStep && (
        <StepContainer stepIconName="check-circle" header="Done" isLastStep>
          {null}
        </StepContainer>
      )}

      {showStoppedStep && (
        <StepContainer stepIconName="stop-circle" header="Stopped" isLastStep>
          {null}
        </StepContainer>
      )}
    </View>
  );
});

export default ExpandedTimelineContent;
