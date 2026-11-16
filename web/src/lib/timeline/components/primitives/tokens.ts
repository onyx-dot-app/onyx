import React from "react";

/**
 * TimelineTokens define the shared layout contract for timeline primitives.
 * Values are applied as CSS variables via TimelineRoot.
 */
export interface TimelineTokens {
  headerRowHeight: string;
  stepHeaderHeight: string;
  stepHeaderRightSectionWidth: string;
  headerPaddingLeft: string;
  headerPaddingRight: string;
  headerTextPaddingX: string;
  headerTextPaddingY: string;
  stepTopPadding: string;
  agentMessagePaddingLeft: string;
  timelineCommonTextPadding: string;
}

/**
 * Default sizing for the timeline layout. Override in TimelineRoot if needed.
 */
export const timelineTokenDefaults: TimelineTokens = {
  headerRowHeight: "var(--spacing-block-36)",
  stepHeaderHeight: "2rem",
  stepHeaderRightSectionWidth: "2.125rem",
  headerPaddingLeft: "0.5rem",
  headerPaddingRight: "0.25rem",
  headerTextPaddingX: "var(--padding-text-4)",
  headerTextPaddingY: "var(--padding-text-2)",
  stepTopPadding: "0.25rem",
  agentMessagePaddingLeft: "0.12rem",
  timelineCommonTextPadding: "0.12rem",
};

/**
 * Returns CSS variables for timeline layout based on defaults + overrides.
 */
export function getTimelineStyles(
  tokens?: Partial<TimelineTokens>
): React.CSSProperties {
  const merged: TimelineTokens = { ...timelineTokenDefaults, ...tokens };
  return {
    "--timeline-header-row-height": merged.headerRowHeight,
    "--timeline-step-header-height": merged.stepHeaderHeight,
    "--timeline-step-header-right-section-width":
      merged.stepHeaderRightSectionWidth,
    "--timeline-header-padding-left": merged.headerPaddingLeft,
    "--timeline-header-padding-right": merged.headerPaddingRight,
    "--timeline-header-text-padding-x": merged.headerTextPaddingX,
    "--timeline-header-text-padding-y": merged.headerTextPaddingY,
    "--timeline-step-top-padding": merged.stepTopPadding,
    "--timeline-agent-message-padding-left": merged.agentMessagePaddingLeft,
    "--timeline-common-text-padding": merged.timelineCommonTextPadding,
  } as React.CSSProperties;
}
