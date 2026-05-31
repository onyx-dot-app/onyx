// timelineTokens.ts — layout spacing scale for the agent timeline.
//
// Ported from the web source of truth:
//   web/src/app/app/message/messageComponents/timeline/primitives/tokens.ts
// On web these are rem strings injected as `--timeline-*` CSS custom
// properties via TimelineRoot. React Native has no CSS variables, so we port
// them to a plain numeric (px) module (1rem = 16px) and pass the numbers
// straight into RN style width/height/padding.
//
// Keep this in sync with the web tokens.ts if the web layout ever changes.

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
//   railWidth 2.25rem, headerRowHeight 2.25rem, stepHeaderHeight 2rem,
//   topConnectorHeight 0.5rem, firstTopSpacerHeight 0.25rem, iconSize 0.75rem,
//   branchIconWrapperSize 1.25rem, branchIconSize 0.75rem,
//   stepHeaderRightSectionWidth 2.125rem, headerPaddingLeft 0.5rem,
//   headerPaddingRight 0.25rem, headerTextPaddingX 0.375rem,
//   headerTextPaddingY 0.125rem, stepTopPadding 0.25rem,
//   agentMessagePaddingLeft 0.12rem, timelineCommonTextPadding 0.12rem
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
