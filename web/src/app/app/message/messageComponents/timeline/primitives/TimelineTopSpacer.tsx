import React from "react";
import { TimelineTopSpacerVariant } from "./tokens";

export interface TimelineTopSpacerProps {
  variant?: TimelineTopSpacerVariant;
}

/**
 * TimelineTopSpacer creates vertical spacing at the top of a step's content.
 * It mirrors connector spacing when the connector is part of layout flow.
 */
export function TimelineTopSpacer({
  variant = "default",
}: TimelineTopSpacerProps) {
  if (variant === "none") {
    return null;
  }

  if (variant === "first") {
    return <div className="h-[var(--timeline-first-top-spacer-height)]" />;
  }

  return <div className="h-[var(--timeline-top-connector-height)]" />;
}

export default TimelineTopSpacer;
