// Web `timeline/primitives/tokens.ts` values baked to px (rem × 16): RN can't use rem/CSS vars for
// dimensions, so these are plain numbers applied via inline `style` (colors/rounding stay classes).
export const timelineTokens = {
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
  agentMessagePaddingLeft: 1.92,
  timelineCommonTextPadding: 1.92,
} as const;

export type TimelineTokens = typeof timelineTokens;
