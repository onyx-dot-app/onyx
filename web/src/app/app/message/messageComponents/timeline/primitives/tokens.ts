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
  branchIconWrapperSize: string;
  branchIconSize: string;
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
  branchIconWrapperSize: "1.25rem",
  branchIconSize: "0.75rem",
  stepHeaderRightSectionWidth: "2.125rem",
  headerPaddingLeft: "0.5rem",
  headerPaddingRight: "0.25rem",
  headerTextPaddingX: "0.375rem",
  headerTextPaddingY: "0.125rem",
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
    "--timeline-rail-width": merged.railWidth,
    "--timeline-header-row-height": merged.headerRowHeight,
    "--timeline-step-header-height": merged.stepHeaderHeight,
    "--timeline-top-connector-height": merged.topConnectorHeight,
    "--timeline-first-top-spacer-height": merged.firstTopSpacerHeight,
    "--timeline-icon-size": merged.iconSize,
    "--timeline-branch-icon-wrapper-size": merged.branchIconWrapperSize,
    "--timeline-branch-icon-size": merged.branchIconSize,
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
