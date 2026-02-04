import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { noProp } from "@/lib/utils";

export interface StoppedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}

/** Header when user stopped/cancelled */
export const StoppedHeader = React.memo(function StoppedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
}: StoppedHeaderProps) {
  return (
    <div
      role="button"
      onClick={onToggle}
      className="flex items-center justify-between w-full rounded-12 p-1"
    >
      <Text as="p" mainUiAction text03>
        Interrupted Thinking
      </Text>
      {collapsible && totalSteps > 0 && (
        <Button
          tertiary
          onClick={noProp(onToggle)}
          rightIcon={isExpanded ? SvgFold : SvgExpand}
          aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
          aria-expanded={isExpanded}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </div>
  );
});
