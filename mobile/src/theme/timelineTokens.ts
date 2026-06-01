// Mirrors web tokens.ts. RN has no CSS variables, so web's rem `--timeline-*`
// custom properties become plain numeric px here (1rem = 16px). Keep in sync.

export interface TimelineTokens {
  railWidth: number;
  headerRowHeight: number;
  stepHeaderHeight: number;
  topConnectorHeight: number;
  firstTopSpacerHeight: number;
  iconSize: number;
  branchIconWrapperSize: number;
  branchIconSize: number;
  stepHeaderRightSectionWidth: number;
  headerPaddingLeft: number;
  headerPaddingRight: number;
  headerTextPaddingX: number;
  headerTextPaddingY: number;
  stepTopPadding: number;
  agentMessagePaddingLeft: number;
  timelineCommonTextPadding: number;
}

export const timelineTokens: TimelineTokens = {
  railWidth: 36,
  headerRowHeight: 36,
  stepHeaderHeight: 32,
  topConnectorHeight: 8,
  firstTopSpacerHeight: 4,
  iconSize: 12,
  branchIconWrapperSize: 20,
  branchIconSize: 12,
  stepHeaderRightSectionWidth: 34,
  headerPaddingLeft: 8,
  headerPaddingRight: 4,
  headerTextPaddingX: 6,
  headerTextPaddingY: 2,
  stepTopPadding: 4,
  agentMessagePaddingLeft: 2,
  timelineCommonTextPadding: 2,
};

// Connector line width — always 1px on web (`w-px`).
export const TIMELINE_CONNECTOR_WIDTH = 1;
