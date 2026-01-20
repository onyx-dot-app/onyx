import { css } from "lit";
import { colors } from "./colors";

/**
 * Onyx Design System - Theme
 * Typography, spacing, and layout tokens from Figma
 */
export const theme = css`
  ${colors}

  :host {
    /* Typography - Hanken Grotesk */
    --onyx-font-family: "Hanken Grotesk", -apple-system, BlinkMacSystemFont,
      "Segoe UI", sans-serif;
    --onyx-font-family-mono: "DM Mono", "Monaco", "Menlo", monospace;

    /* Font Sizes */
    --onyx-font-size-small: 10px;
    --onyx-font-size-secondary: 12px;
    --onyx-font-size-sm: 13px;
    --onyx-font-size-main: 14px;
    --onyx-font-size-label: 16px;

    /* Line Heights */
    --onyx-line-height-small: 12px;
    --onyx-line-height-secondary: 16px;
    --onyx-line-height-main: 20px;
    --onyx-line-height-label: 24px;
    --onyx-line-height-section: 28px;
    --onyx-line-height-headline: 36px;

    /* Font Weights */
    --onyx-weight-regular: 400;
    --onyx-weight-medium: 500;
    --onyx-weight-semibold: 600;

    /* Content Heights */
    --onyx-height-content-secondary: 12px;
    --onyx-height-content-main: 16px;
    --onyx-height-content-label: 18px;
    --onyx-height-content-section: 24px;

    /* Border Radius - from Figma */
    --onyx-radius-04: 4px;
    --onyx-radius-08: 8px;
    --onyx-radius-12: 12px;
    --onyx-radius-16: 16px;
    --onyx-radius-round: 1000px;

    /* Spacing - Block */
    --onyx-space-block-1x: 4px;
    --onyx-space-block-2x: 8px;
    --onyx-space-block-3x: 12px;
    --onyx-space-block-4x: 16px;
    --onyx-space-block-6x: 24px;

    /* Spacing - Inline */
    --onyx-space-inline-0: 0px;
    --onyx-space-inline-0_5x: 2px;
    --onyx-space-inline-1x: 4px;

    /* Legacy spacing aliases (for compatibility) */
    --onyx-space-2xs: var(--onyx-space-block-1x);
    --onyx-space-xs: var(--onyx-space-block-2x);
    --onyx-space-sm: var(--onyx-space-block-3x);
    --onyx-space-md: var(--onyx-space-block-4x);
    --onyx-space-lg: var(--onyx-space-block-6x);

    /* Padding */
    --onyx-padding-icon-0: 0px;
    --onyx-padding-icon-0_5x: 2px;
    --onyx-padding-text-0_5x: 2px;
    --onyx-padding-text-1x: 4px;

    /* Icon Weights (stroke-width) */
    --onyx-icon-weight-secondary: 1px;
    --onyx-icon-weight-main: 1.5px;
    --onyx-icon-weight-section: 2px;

    /* Z-index */
    --onyx-z-launcher: 9999;
    --onyx-z-widget: 10000;

    /* Transitions */
    --onyx-transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
    --onyx-transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1);
  }

  * {
    box-sizing: border-box;
  }
`;
