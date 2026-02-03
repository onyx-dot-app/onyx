import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import { formatDurationSeconds } from "@/lib/time";

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
      className="flex items-center justify-between w-full hover:bg-background-tint-00 transition-colors duration-200 rounded-12 p-1"
    >
      <Text as="p" mainUiAction text03>
        {isExpanded ? durationText : imageText ?? durationText}
      </Text>
      {collapsible &&
        totalSteps > 0 &&
        (isExpanded ? (
          <IconButton
            tertiary
            onClick={onToggle}
            icon={SvgFold}
            aria-label="Collapse timeline"
            aria-expanded={true}
          />
        ) : (
          <Button
            tertiary
            onClick={onToggle}
            rightIcon={SvgExpand}
            aria-label="Expand timeline"
            aria-expanded={false}
          >
            {totalSteps} {totalSteps === 1 ? "step" : "steps"}
          </Button>
        ))}
    </div>
  );
});
