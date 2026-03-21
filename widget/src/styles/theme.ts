import { css } from "lit";
import { colors } from "./colors";

/**
 * Activa Design System - Theme
 * Typography, spacing, and layout tokens from Figma
 */
export const theme = css`
  ${colors}

  :host {
    /* Typography - Hanken Grotesk */
    --activa-font-family: "Hanken Grotesk", -apple-system, BlinkMacSystemFont,
      "Segoe UI", sans-serif;
    --activa-font-family-mono: "DM Mono", "Monaco", "Menlo", monospace;

    /* Font Sizes */
    --activa-font-size-small: 10px;
    --activa-font-size-secondary: 12px;
    --activa-font-size-sm: 13px;
    --activa-font-size-main: 14px;
    --activa-font-size-label: 16px;

    /* Line Heights */
    --activa-line-height-small: 12px;
    --activa-line-height-secondary: 16px;
    --activa-line-height-main: 20px;
    --activa-line-height-label: 24px;
    --activa-line-height-section: 28px;
    --activa-line-height-headline: 36px;

    /* Font Weights */
    --activa-weight-regular: 400;
    --activa-weight-medium: 500;
    --activa-weight-semibold: 600;

    /* Content Heights */
    --activa-height-content-secondary: 12px;
    --activa-height-content-main: 16px;
    --activa-height-content-label: 18px;
    --activa-height-content-section: 24px;

    /* Border Radius - from Figma */
    --activa-radius-04: 4px;
    --activa-radius-08: 8px;
    --activa-radius-12: 12px;
    --activa-radius-16: 16px;
    --activa-radius-round: 1000px;

    /* Spacing - Block */
    --activa-space-block-1x: 4px;
    --activa-space-block-2x: 8px;
    --activa-space-block-3x: 12px;
    --activa-space-block-4x: 16px;
    --activa-space-block-6x: 24px;

    /* Spacing - Inline */
    --activa-space-inline-0: 0px;
    --activa-space-inline-0_5x: 2px;
    --activa-space-inline-1x: 4px;

    /* Legacy spacing aliases (for compatibility) */
    --activa-space-2xs: var(--activa-space-block-1x);
    --activa-space-xs: var(--activa-space-block-2x);
    --activa-space-sm: var(--activa-space-block-3x);
    --activa-space-md: var(--activa-space-block-4x);
    --activa-space-lg: var(--activa-space-block-6x);

    /* Padding */
    --activa-padding-icon-0: 0px;
    --activa-padding-icon-0_5x: 2px;
    --activa-padding-text-0_5x: 2px;
    --activa-padding-text-1x: 4px;

    /* Icon Weights (stroke-width) */
    --activa-icon-weight-secondary: 1px;
    --activa-icon-weight-main: 1.5px;
    --activa-icon-weight-section: 2px;

    /* Z-index */
    --activa-z-launcher: 9999;
    --activa-z-widget: 10000;

    /* Transitions */
    --activa-transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
    --activa-transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1);
  }

  * {
    box-sizing: border-box;
  }
`;
