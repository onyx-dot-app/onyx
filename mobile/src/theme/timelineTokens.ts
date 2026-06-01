// timelineTokens.ts — layout spacing scale for the agent timeline.
//
// Mirrors web tokens.ts. RN has no CSS variables, so web's rem `--timeline-*`
// custom properties become plain numeric px here (1rem = 16px). Keep in sync.

export interface TimelineTokens {
  /** Width of the left rail column (avatar + connector + icon). */
  railWidth: number;
  /** Height of the header row (avatar row). */
  headerRowHeight: number;
  /** Height of a step's header row (status text + collapse button). */
  stepHeaderHeight: number;
  /** Height of the connector segment above a step icon. */
  topConnectorHeight: number;
  /** Smaller top spacer used for the first step. */
  firstTopSpacerHeight: number;
  /** Rendered size of a step icon. */
  iconSize: number;
  /** Size of the branch (parallel) icon wrapper box. */
  branchIconWrapperSize: number;
  /** Rendered size of the branch icon. */
  branchIconSize: number;
  /** Fixed width of the step header's right section (collapse button slot). */
  stepHeaderRightSectionWidth: number;
  headerPaddingLeft: number;
  headerPaddingRight: number;
  headerTextPaddingX: number;
  headerTextPaddingY: number;
  /** Vertical padding at the top of a step. */
  stepTopPadding: number;
  /** Left padding applied to the whole timeline root. */
  agentMessagePaddingLeft: number;
  /** Common left padding for long-form timeline text (reasoning, etc.). */
  timelineCommonTextPadding: number;
}

// rem -> px @16. Values mirror web timelineTokenDefaults exactly.
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

/** Width of the connector line (always 1px on web: `w-px`). */
export const TIMELINE_CONNECTOR_WIDTH = 1;
