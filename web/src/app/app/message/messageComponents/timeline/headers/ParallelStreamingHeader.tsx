import React, { useMemo } from "react";
import { useTranslations } from "next-intl";
import { SvgFold, SvgExpand } from "@opal/icons";
import { Button, Tabs } from "@opal/components";
import { TurnGroup } from "../transformers";
import {
  getToolIcon,
  getToolName,
  isToolComplete,
} from "../../toolDisplayHelpers";

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
            step.packets.length > 0 && !isToolComplete(step.packets),
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
                {getToolIcon(step.packets)}
                {getToolName(step.packets, t)}
              </span>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs>
    );
  }
);
