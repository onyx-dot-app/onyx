import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { cn, noProp } from "@/lib/utils";

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
  const isInteractive = collapsible && totalSteps > 0;

  return (
    <div
      role={isInteractive ? "button" : undefined}
      onClick={isInteractive ? onToggle : undefined}
      className={cn(
        "flex items-center justify-between w-full rounded-12",
        isInteractive ? "cursor-pointer" : "cursor-default"
      )}
      aria-disabled={isInteractive ? undefined : true}
    >
      <div className="px-[var(--timeline-header-text-padding-x)] py-[var(--timeline-header-text-padding-y)]">
        <Text as="p" mainUiAction text03>
          Interrupted Thinking
        </Text>
      </div>

      {isInteractive && (
        <Button
          prominence="tertiary"
          size="md"
          onClick={noProp(onToggle)}
          rightIcon={isExpanded ? SvgFold : SvgExpand}
          aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
          aria-expanded={isExpanded}
        >
          {`${totalSteps} ${totalSteps === 1 ? "step" : "steps"}`}
        </Button>
      )}
    </div>
  );
});
