// The selected tab also decides which branch the collapsed preview below shows, so the shell owns
// `activeTab` rather than this header.
import { memo, useMemo } from "react";

import { getToolName, isToolComplete } from "@/chat/timeline/toolDisplay";
import type { TurnGroup } from "@/chat/timeline/transformers";
import { getToolIcon } from "@/components/chat/timeline/toolIcons";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import SvgExpand from "@/icons/expand";
import SvgFold from "@/icons/fold";

export interface ParallelStreamingHeaderProps {
  steps: TurnGroup["steps"];
  activeTab: string;
  onTabChange: (tab: string) => void;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}

export const ParallelStreamingHeader = memo(function ParallelStreamingHeader({
  steps,
  activeTab,
  onTabChange,
  collapsible,
  isExpanded,
  onToggle,
}: ParallelStreamingHeaderProps) {
  const loadingStates = useMemo(
    () =>
      new Map(
        steps.map((step) => [
          step.key,
          step.packets.length > 0 && !isToolComplete(step.packets),
        ]),
      ),
    [steps],
  );

  return (
    <Tabs value={activeTab} onValueChange={onTabChange}>
      <Tabs.List
        rightChildren={
          collapsible ? (
            <Button
              prominence="tertiary"
              size="sm"
              onPress={onToggle}
              icon={isExpanded ? SvgFold : SvgExpand}
              accessibilityLabel={
                isExpanded ? "Collapse timeline" : "Expand timeline"
              }
            />
          ) : undefined
        }
      >
        {steps.map((step) => (
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
  );
});

export default ParallelStreamingHeader;
