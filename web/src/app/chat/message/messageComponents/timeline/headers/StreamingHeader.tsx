import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import { useStreamingDuration } from "../hooks";
import { formatDurationSeconds } from "@/lib/time";

export interface StreamingHeaderProps {
  headerText: string;
  collapsible: boolean;
  buttonTitle?: string;
  isExpanded: boolean;
  onToggle: () => void;
  streamingStartTime?: number;
}

/** Header during streaming - shimmer text with current activity */
export const StreamingHeader = React.memo(function StreamingHeader({
  headerText,
  collapsible,
  buttonTitle,
  isExpanded,
  onToggle,
  streamingStartTime,
}: StreamingHeaderProps) {
  const elapsedSeconds = useStreamingDuration(true, streamingStartTime);
  const showElapsedTime =
    isExpanded && streamingStartTime && elapsedSeconds > 0;

  return (
    <>
      <Text
        as="p"
        mainUiAction
        text03
        className="animate-shimmer bg-[length:200%_100%] bg-[linear-gradient(90deg,var(--shimmer-base)_10%,var(--shimmer-highlight)_40%,var(--shimmer-base)_70%)] bg-clip-text text-transparent"
      >
        {headerText}
      </Text>
      {collapsible &&
        (buttonTitle ? (
          <Button
            tertiary
            onClick={onToggle}
            rightIcon={isExpanded ? SvgFold : SvgExpand}
            aria-expanded={isExpanded}
          >
            {buttonTitle}
          </Button>
        ) : showElapsedTime ? (
          <Button
            tertiary
            onClick={onToggle}
            rightIcon={SvgFold}
            aria-label="Collapse timeline"
            aria-expanded={true}
          >
            {formatDurationSeconds(elapsedSeconds)}
          </Button>
        ) : (
          <IconButton
            tertiary
            onClick={onToggle}
            icon={isExpanded ? SvgFold : SvgExpand}
            aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
            aria-expanded={isExpanded}
          />
        ))}
    </>
  );
});
