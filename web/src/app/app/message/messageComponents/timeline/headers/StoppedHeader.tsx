import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";

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
    <>
      <Text as="p" mainUiAction text03>
        Stopped Thinking
      </Text>
      {collapsible && (
        <Button
          tertiary
          onClick={onToggle}
          rightIcon={isExpanded ? SvgFold : SvgExpand}
          aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
          aria-expanded={isExpanded}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </>
  );
});
