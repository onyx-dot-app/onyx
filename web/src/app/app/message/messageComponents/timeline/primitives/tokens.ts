import React from "react";

/**
 * TimelineTokens define the shared layout contract for timeline primitives.
 * Values are applied as CSS variables via TimelineRoot.
 */
export interface TimelineTokens {
  railWidth: string;
  headerRowHeight: string;
  stepHeaderHeight: string;
  topConnectorHeight: string;
  firstTopSpacerHeight: string;
  iconSize: string;
  iconWrapperSize: string;
  branchIconWrapperSize: string;
  branchIconSize: string;
  contentPaddingLeft: string;
  stepHeaderRightSectionWidth: string;
  contentPaddingBottom: string;
  headerPaddingLeft: string;
  headerPaddingRight: string;
  agentMessagePaddingLeft: string;
  timelineCommonTextPadding: string;
}

/**
 * Controls the top spacer inside TimelineStepContent.
 * - default: reserve space equal to the top connector height.
 * - first: smaller spacer used for the first step.
 * - none: no spacer (use when connector is drawn outside layout flow).
 */
export type TimelineTopSpacerVariant = "default" | "first" | "none";

/**
 * Default sizing for the timeline layout. Override in TimelineRoot if needed.
 */
export const timelineTokenDefaults: TimelineTokens = {
  railWidth: "2.25rem",
  headerRowHeight: "2.25rem",
  stepHeaderHeight: "2rem",
  topConnectorHeight: "0.5rem",
  firstTopSpacerHeight: "0.25rem",
  iconSize: "0.75rem",
  iconWrapperSize: "2rem",
  branchIconWrapperSize: "1.25rem",
  branchIconSize: "0.75rem",
  contentPaddingLeft: "0.5rem",
  stepHeaderRightSectionWidth: "2.125rem",
  contentPaddingBottom: "0.5rem",
  headerPaddingLeft: "0.5rem",
  headerPaddingRight: "0.25rem",
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
    "--timeline-rail-width": merged.railWidth,
    "--timeline-header-row-height": merged.headerRowHeight,
    "--timeline-step-header-height": merged.stepHeaderHeight,
    "--timeline-top-connector-height": merged.topConnectorHeight,
    "--timeline-first-top-spacer-height": merged.firstTopSpacerHeight,
    "--timeline-icon-size": merged.iconSize,
    "--timeline-icon-wrapper-size": merged.iconWrapperSize,
    "--timeline-branch-icon-wrapper-size": merged.branchIconWrapperSize,
    "--timeline-branch-icon-size": merged.branchIconSize,
    "--timeline-content-padding-left": merged.contentPaddingLeft,
    "--timeline-step-header-right-section-width":
      merged.stepHeaderRightSectionWidth,
    "--timeline-content-padding-bottom": merged.contentPaddingBottom,
    "--timeline-header-padding-left": merged.headerPaddingLeft,
    "--timeline-header-padding-right": merged.headerPaddingRight,
    "--timeline-agent-message-padding-left": merged.agentMessagePaddingLeft,
    "--timeline-common-text-padding": merged.timelineCommonTextPadding,
  } as React.CSSProperties;
}
