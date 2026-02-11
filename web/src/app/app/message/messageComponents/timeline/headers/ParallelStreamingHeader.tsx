import React, { useMemo } from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import Tabs from "@/refresh-components/Tabs";
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
      <Tabs value={activeTab} onValueChange={onTabChange}>
        <Tabs.List
          variant="pill"
          enableScrollArrows
          rightContent={
            collapsible ? (
              <IconButton
                tertiary
                onClick={onToggle}
                icon={isExpanded ? SvgFold : SvgExpand}
                aria-label={
                  isExpanded ? "Collapse timeline" : "Expand timeline"
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
              variant="pill"
              isLoading={loadingStates.get(step.key)}
            >
              <span className="flex items-center gap-1.5">
                {getToolIcon(step.packets)}
                {getToolName(step.packets)}
              </span>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs>
    );
  }
);
