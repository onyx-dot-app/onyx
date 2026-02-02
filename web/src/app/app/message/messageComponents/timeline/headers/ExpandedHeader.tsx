import React from "react";
import { SvgFold } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import { formatDurationSeconds } from "@/lib/time";

export interface ExpandedHeaderProps {
  collapsible: boolean;
  onToggle: () => void;
  processingDurationSeconds?: number;
}

/** Header when completed + expanded */
export const ExpandedHeader = React.memo(function ExpandedHeader({
  collapsible,
  onToggle,
  processingDurationSeconds,
}: ExpandedHeaderProps) {
  const durationText =
    processingDurationSeconds !== undefined
      ? `Thought for ${formatDurationSeconds(processingDurationSeconds)}`
      : "Thought for some time";

  return (
    <>
      <Text as="p" mainUiAction text03>
        {durationText}
      </Text>
      {collapsible && (
        <IconButton
          tertiary
          onClick={onToggle}
          icon={SvgFold}
          aria-label="Collapse timeline"
          aria-expanded={true}
        />
      )}
    </>
  );
});
