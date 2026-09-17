import React, { useMemo } from "react";
import { useTranslations } from "next-intl";
import { SvgFold, SvgExpand } from "@opal/icons";
import { Button, Tabs } from "@opal/components";
import { TurnGroup } from "@/app/app/message/messageComponents/timeline/transformers";
import {
  getToolIcon,
  getToolName,
  isToolComplete,
} from "@/app/app/message/messageComponents/toolDisplayHelpers";

export interface ParallelStreamingHeaderProps {
  steps: TurnGroup["steps"];
  activeTab: string;
  onTabChange: (tab: string) => void;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}

/** Header during streaming with parallel tools - tabs only */
export const ParallelStreamingHeader = React.memo(
  function ParallelStreamingHeader({
    steps,
    activeTab,
    onTabChange,
    collapsible,
    isExpanded,
    onToggle,
  }: ParallelStreamingHeaderProps) {
    const t = useTranslations("chat.messages.timeline");

    // Memoized loading states for each step
    const loadingStates = useMemo(
      () =>
        new Map(
          steps.map((step) => [
            step.key,
            step.items.length > 0 && !isToolComplete(step.items),
          ])
        ),
      [steps]
    );

    return (
      <Tabs value={activeTab} onValueChange={onTabChange} variant="pill">
        <Tabs.List
          enableScrollArrows
          rightChildren={
            collapsible ? (
              <Button
                prominence="tertiary"
                size="sm"
                onClick={onToggle}
                icon={isExpanded ? SvgFold : SvgExpand}
                aria-label={
                  isExpanded
                    ? t("collapseButton.ariaLabel")
                    : t("expandButton.ariaLabel")
                }
                aria-expanded={isExpanded}
              />
            ) : undefined
          }
        >
          {steps.map((step) => (
            <Tabs.Trigger
              key={step.key}
              value={step.key}
              isLoading={loadingStates.get(step.key)}
            >
              <span className="flex items-center gap-1.5">
                {getToolIcon(step.items)}
                {getToolName(step.items, t)}
              </span>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs>
    );
  }
);
