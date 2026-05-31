// ParallelTimelineTabs.tsx — renders a parallel (or coding-agent) turn group as
// a branch row with a tab strip + the active tab's content. Functional port of
// web ParallelTimelineTabs (Opal pill Tabs -> horizontal ScrollView).

import { memo, useEffect, useState } from "react";
import { View, Pressable, ScrollView } from "react-native";

import type { StopReason } from "@/lib/types";
import type { FullChatState } from "@/components/message/interfaces";
import type { TurnGroup } from "@/state/timeline/transformers";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { Text, Spinner } from "@/components/opal";
import { TimelineRow } from "@/components/message/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/components/message/timeline/primitives/TimelineSurface";
import { TimelineTopSpacer } from "@/components/message/timeline/primitives/TimelineTopSpacer";
import { TimelineIcon } from "@/components/message/timeline/toolIcon";
import {
  TimelineRendererComponent,
  type TimelineRendererOutput,
} from "@/components/message/timeline/TimelineRendererComponent";
import { TimelineStepComposer } from "@/components/message/timeline/TimelineStepComposer";
import {
  getToolName,
  getToolIconName,
  isToolComplete,
} from "@/state/timeline/toolDisplayHelpers";

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
  const colors = useThemeColors();
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
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ alignItems: "center", gap: 6, paddingHorizontal: 4 }}
        >
          {turnGroup.steps.map((step) => {
            const active = step.key === activeTab;
            const loading = !stopPacketSeen && !isToolComplete(step.packets);
            return (
              <Pressable
                key={step.key}
                onPress={() => setActiveTab(step.key)}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  paddingHorizontal: 8,
                  paddingVertical: 4,
                  borderRadius: radii["08"],
                  backgroundColor: active
                    ? colors["background-tint-02"]
                    : "transparent",
                }}
              >
                {loading ? (
                  <Spinner size={12} color="text-03" />
                ) : (
                  <TimelineIcon
                    name={getToolIconName(step.packets)}
                    size={12}
                    color={active ? "text-04" : "text-02"}
                  />
                )}
                <Text font="main-ui-muted" color={active ? "text-04" : "text-03"}>
                  {getToolName(step.packets)}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>

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
