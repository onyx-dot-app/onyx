"use client";

import React from "react";
import { SvgFold, SvgExpand } from "@opal/icons";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { useStreamingDuration } from "../hooks/useStreamingDuration";
import { formatDurationSeconds } from "@/lib/time";

export interface StreamingHeaderProps {
  headerText: string;
  collapsible: boolean;
  buttonTitle?: string;
  isExpanded: boolean;
  onToggle: () => void;
  streamingStartTime?: number;
  /** Tool processing duration from backend (freezes timer when available) */
  toolProcessingDuration?: number;
}

/** Header during streaming - shimmer text with current activity */
export const StreamingHeader = React.memo(function StreamingHeader({
  headerText,
  collapsible,
  buttonTitle,
  isExpanded,
  onToggle,
  streamingStartTime,
  toolProcessingDuration,
}: StreamingHeaderProps) {
  // Use backend duration when available, otherwise continue live timer
  const elapsedSeconds = useStreamingDuration(
    toolProcessingDuration === undefined, // Stop updating when we have backend duration
    streamingStartTime,
    toolProcessingDuration
  );
  const showElapsedTime =
    isExpanded && streamingStartTime && elapsedSeconds > 0;

  return (
    <>
      <div className="px-[var(--timeline-header-text-padding-x)] py-[var(--timeline-header-text-padding-y)]">
        <Text
          as="p"
          mainUiAction
          text03
          className="animate-shimmer bg-[length:200%_100%] bg-[linear-gradient(90deg,var(--shimmer-base)_10%,var(--shimmer-highlight)_40%,var(--shimmer-base)_70%)] bg-clip-text text-transparent"
        >
          {headerText}
        </Text>
      </div>

      {collapsible &&
        (buttonTitle ? (
          <Button
            prominence="tertiary"
            size="md"
            onClick={onToggle}
            rightIcon={isExpanded ? SvgFold : SvgExpand}
            aria-expanded={isExpanded}
          >
            {buttonTitle}
          </Button>
        ) : showElapsedTime ? (
          <Button
            prominence="tertiary"
            size="md"
            onClick={onToggle}
            rightIcon={SvgFold}
            aria-label="Collapse timeline"
            aria-expanded={true}
          >
            {formatDurationSeconds(elapsedSeconds)}
          </Button>
        ) : (
          <Button
            prominence="tertiary"
            size="md"
            onClick={onToggle}
            icon={isExpanded ? SvgFold : SvgExpand}
            aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
            aria-expanded={isExpanded}
          />
        ))}
    </>
  );
});
