// Native mirror of web ParallelTimelineTabs (pill Tabs -> horizontal ScrollView).

import { memo, useEffect, useState } from "react";
import { View } from "react-native";

import type { StopReason } from "@/lib/types";
import type { FullChatState } from "@/components/message/interfaces";
import type { TurnGroup } from "@/state/timeline/transformers";
import { TimelineRow } from "@/components/message/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/components/message/timeline/primitives/TimelineSurface";
import { TimelineTopSpacer } from "@/components/message/timeline/primitives/TimelineTopSpacer";
import { TimelinePillTabs } from "@/components/message/timeline/primitives/TimelinePillTabs";
import { TimelineIcon } from "@/components/message/timeline/toolIcon";
import {
  TimelineRendererComponent,
  type TimelineRendererOutput,
} from "@/components/message/timeline/TimelineRendererComponent";
import { TimelineStepComposer } from "@/components/message/timeline/TimelineStepComposer";
import { isToolComplete } from "@/state/timeline/toolDisplayHelpers";

export interface ParallelTimelineTabsProps {
  turnGroup: TurnGroup;
  chatState: FullChatState;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  isLastTurnGroup: boolean;
  isFirstTurnGroup: boolean;
}

export const ParallelTimelineTabs = memo(function ParallelTimelineTabs({
  turnGroup,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastTurnGroup,
  isFirstTurnGroup,
}: ParallelTimelineTabsProps) {
  const [activeTab, setActiveTab] = useState(turnGroup.steps[0]?.key ?? "");

  // Keep activeTab valid as steps stream in.
  useEffect(() => {
    if (!turnGroup.steps.some((s) => s.key === activeTab)) {
      setActiveTab(turnGroup.steps[0]?.key ?? "");
    }
  }, [turnGroup.steps, activeTab]);

  const activeStep =
    turnGroup.steps.find((s) => s.key === activeTab) ?? turnGroup.steps[0];

  const renderStep = (results: TimelineRendererOutput) => (
    <TimelineStepComposer
      results={results}
      isLastStep
      isFirstStep={false}
      isSingleStep={false}
      collapsible
    />
  );

  return (
    <TimelineRow
      railVariant="rail"
      icon={<TimelineIcon name="branch" size={12} color="text-02" />}
      isFirst={isFirstTurnGroup}
      isLast={isLastTurnGroup}
    >
      <TimelineSurface roundedBottom={isLastTurnGroup}>
        <TimelineTopSpacer variant="default" />
        <TimelinePillTabs
          steps={turnGroup.steps}
          activeKey={activeTab}
          onSelect={setActiveTab}
          loadingPredicate={(step) =>
            !stopPacketSeen && !isToolComplete(step.packets)
          }
        />

        {activeStep && (
          <View style={{ paddingHorizontal: 4, paddingBottom: 4 }}>
            <TimelineRendererComponent
              key={`${activeStep.key}-tab`}
              packets={activeStep.packets}
              chatState={chatState}
              animate={!stopPacketSeen}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
              defaultExpanded
              isLastStep
            >
              {renderStep}
            </TimelineRendererComponent>
          </View>
        )}
      </TimelineSurface>
    </TimelineRow>
  );
});

export default ParallelTimelineTabs;
