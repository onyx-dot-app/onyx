import { useCallback, useMemo, useState } from "react";
import { View } from "react-native";

import { getToolName, isToolComplete } from "@/chat/timeline/toolDisplay";
import type { TurnGroup } from "@/chat/timeline/transformers";
import type { StopReason } from "@/chat/streamingModels";
import type {
  FullChatState,
  TimelineRendererResult,
} from "@/components/chat/renderers/timelineContract";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Tabs } from "@/components/ui/tabs";
import SvgBranch from "@/icons/branch";
import SvgExpand from "@/icons/expand";
import SvgFold from "@/icons/fold";

import { TimelineRendererComponent } from "./TimelineRendererComponent";
import { TimelineStepComposer } from "./TimelineStepComposer";
import { getToolIcon } from "./toolIcons";
import { timelineTokens } from "./primitives/timelineTokens";
import { TimelineRow } from "./primitives/TimelineRow";
import { TimelineSurface } from "./primitives/TimelineSurface";
import { TimelineTopSpacer } from "./primitives/TimelineTopSpacer";

export interface ParallelTimelineTabsProps {
  turnGroup: TurnGroup;
  chatState: FullChatState;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  // Drives the trailing connector, on whichever row ends up last in the group.
  isLastTurnGroup: boolean;
  isFirstTurnGroup: boolean;
}

export function ParallelTimelineTabs({
  turnGroup,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastTurnGroup,
  isFirstTurnGroup,
}: ParallelTimelineTabsProps) {
  const [activeTab, setActiveTab] = useState(turnGroup.steps[0]?.key ?? "");
  const [isExpanded, setIsExpanded] = useState(true);
  const handleToggle = useCallback(() => setIsExpanded((prev) => !prev), []);

  const topSpacerVariant = isFirstTurnGroup ? "first" : "none";
  // Folding a finished group leaves just the tabs; folding a running one still shows its output.
  const shouldShowResults = !(!isExpanded && stopPacketSeen);

  const activeStep = useMemo(
    () => turnGroup.steps.find((step) => step.key === activeTab),
    [turnGroup.steps, activeTab],
  );

  const loadingStates = useMemo(
    () =>
      new Map(
        turnGroup.steps.map((step) => [
          step.key,
          !stopPacketSeen &&
            step.packets.length > 0 &&
            !isToolComplete(step.packets),
        ]),
      ),
    [turnGroup.steps, stopPacketSeen],
  );

  const renderTabContent = useCallback(
    (results: TimelineRendererResult[]) => (
      <TimelineStepComposer
        results={results}
        isLastStep={isLastTurnGroup}
        isFirstStep={false}
        isSingleStep={false}
        collapsible
      />
    ),
    [isLastTurnGroup],
  );

  const hasActivePackets = Boolean(activeStep && activeStep.packets.length > 0);
  const headerIsLast =
    isLastTurnGroup && (!shouldShowResults || !hasActivePackets);

  return (
    <View className="w-full flex-col">
      <TimelineRow
        railVariant="rail"
        isFirst={isFirstTurnGroup}
        isLast={headerIsLast}
        icon={
          <Icon
            as={SvgBranch}
            size={timelineTokens.branchIconSize}
            className="text-text-02"
          />
        }
      >
        <TimelineSurface className="flex-1" roundedBottom={headerIsLast}>
          <TimelineTopSpacer variant={topSpacerVariant} />
          <View
            className="flex-row items-center"
            style={{
              minHeight: timelineTokens.stepHeaderHeight,
              paddingLeft: timelineTokens.headerPaddingLeft,
              paddingRight: timelineTokens.headerPaddingRight,
            }}
          >
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <Tabs.List
                rightChildren={
                  <Button
                    prominence="tertiary"
                    size="sm"
                    onPress={handleToggle}
                    icon={isExpanded ? SvgFold : SvgExpand}
                    accessibilityLabel={
                      isExpanded ? "Collapse branch" : "Expand branch"
                    }
                  />
                }
              >
                {turnGroup.steps.map((step) => (
                  <Tabs.Trigger
                    key={step.key}
                    value={step.key}
                    icon={getToolIcon(step.packets)}
                    isLoading={loadingStates.get(step.key)}
                  >
                    {getToolName(step.packets)}
                  </Tabs.Trigger>
                ))}
              </Tabs.List>
            </Tabs>
          </View>
        </TimelineSurface>
      </TimelineRow>

      {shouldShowResults && activeStep ? (
        <TimelineRendererComponent
          // Re-key so switching tab or folding remounts the renderer at the right expansion.
          key={`${activeTab}-${isExpanded}`}
          packets={activeStep.packets}
          chatState={chatState}
          animate={!stopPacketSeen}
          stopPacketSeen={stopPacketSeen}
          stopReason={stopReason}
          defaultExpanded={isExpanded}
          isLastStep={isLastTurnGroup}
        >
          {renderTabContent}
        </TimelineRendererComponent>
      ) : null}
    </View>
  );
}

export default ParallelTimelineTabs;
