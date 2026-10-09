import { memo } from "react";
import { View } from "react-native";

import { isCodingAgentPackets } from "@/chat/timeline/packetHelpers";
import type { TurnGroup } from "@/chat/timeline/transformers";
import type { StopReason } from "@/chat/streamingModels";
import type { FullChatState } from "@/components/chat/renderers/timelineContract";
import SvgCheckCircle from "@/icons/check-circle";
import SvgStopCircle from "@/icons/stop-circle";

import { ParallelTimelineTabs } from "./ParallelTimelineTabs";
import { StepContainer } from "./StepContainer";
import { TimelineStep } from "./TimelineStep";

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
    <View className="w-full">
      {turnGroups.map((turnGroup, turnIdx) => {
        // Coding agents always take the tab chrome, so one looks the same as several side by side.
        const renderAsParallelTabs =
          turnGroup.isParallel ||
          turnGroup.steps.some((step) => isCodingAgentPackets(step.packets));

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

        return turnGroup.steps.map((step, stepIdx) => (
          <TimelineStep
            key={step.key}
            step={step}
            chatState={chatState}
            stopPacketSeen={stopPacketSeen}
            stopReason={stopReason}
            isLastStep={
              turnIdx === turnGroups.length - 1 &&
              stepIdx === turnGroup.steps.length - 1 &&
              !hasDoneIndicator &&
              !userStopped
            }
            isFirstStep={turnIdx === 0 && stepIdx === 0}
            isSingleStep={isSingleStep}
            isStreaming={!stopPacketSeen && !userStopped}
          />
        ));
      })}

      {showDoneStep ? (
        <StepContainer stepIcon={SvgCheckCircle} header="Done" isLastStep>
          {null}
        </StepContainer>
      ) : null}

      {showStoppedStep ? (
        <StepContainer stepIcon={SvgStopCircle} header="Stopped" isLastStep>
          {null}
        </StepContainer>
      ) : null}
    </View>
  );
});

export default ExpandedTimelineContent;
