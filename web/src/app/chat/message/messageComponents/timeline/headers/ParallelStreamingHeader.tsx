import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import Tabs from "@/refresh-components/Tabs";
import { TurnGroup } from "../transformers";
import { getToolIcon, getToolName } from "../../toolDisplayHelpers";

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
    return (
      <Tabs value={activeTab} onValueChange={onTabChange}>
        <div className="flex items-center justify-between w-full gap-2">
          <Tabs.List variant="pill">
            {steps.map((step) => (
              <Tabs.Trigger key={step.key} value={step.key} variant="pill">
                <span className="flex items-center gap-1.5">
                  {getToolIcon(step.packets)}
                  {getToolName(step.packets)}
                </span>
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          {collapsible && (
            <IconButton
              tertiary
              onClick={onToggle}
              icon={isExpanded ? SvgFold : SvgExpand}
              aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
              aria-expanded={isExpanded}
            />
          )}
        </div>
      </Tabs>
    );
  }
);
