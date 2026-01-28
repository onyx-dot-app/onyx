import React from "react";
import { SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { formatDurationSeconds } from "@/lib/time";

export interface CollapsedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  onToggle: () => void;
  processingDurationSeconds?: number;
  generatedImageCount?: number;
}

/** Header when completed + collapsed - duration text + step count */
export const CollapsedHeader = React.memo(function CollapsedHeader({
  totalSteps,
  collapsible,
  onToggle,
  processingDurationSeconds = 0,
  generatedImageCount = 0,
}: CollapsedHeaderProps) {
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
    <>
      <div className="flex flex-col">
        {!imageText && (
          <Text as="p" mainUiAction text03>
            {durationText}
          </Text>
        )}
        {imageText && (
          <Text as="p" mainUiAction text03>
            {imageText}
          </Text>
        )}
      </div>
      {collapsible && totalSteps > 0 && (
        <Button
          tertiary
          onClick={onToggle}
          rightIcon={SvgExpand}
          aria-label="Expand timeline"
          aria-expanded={false}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </>
  );
});
