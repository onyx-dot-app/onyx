import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { formatDurationSeconds } from "@/lib/time";
import { noProp } from "@/lib/utils";

export interface CompletedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  processingDurationSeconds?: number;
  generatedImageCount?: number;
}

/** Header when completed - handles both collapsed and expanded states */
export const CompletedHeader = React.memo(function CompletedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
  processingDurationSeconds = 0,
  generatedImageCount = 0,
}: CompletedHeaderProps) {
  const durationText = processingDurationSeconds
    ? `Thought for ${formatDurationSeconds(processingDurationSeconds)}`
    : "Thought for some time";

  const imageText =
    generatedImageCount > 0
      ? `Generated ${generatedImageCount} ${
          generatedImageCount === 1 ? "image" : "images"
        }`
      : null;

  return (
    <div
      role="button"
      onClick={onToggle}
      className="flex items-center justify-between w-full rounded-12 p-1"
    >
      <Text as="p" mainUiAction text03>
        {isExpanded ? durationText : imageText ?? durationText}
      </Text>
      {collapsible && totalSteps > 0 && (
        <Button
          tertiary
          onClick={noProp(onToggle)}
          rightIcon={isExpanded ? SvgFold : SvgExpand}
          aria-label="Expand timeline"
          aria-expanded={isExpanded}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </div>
  );
});
