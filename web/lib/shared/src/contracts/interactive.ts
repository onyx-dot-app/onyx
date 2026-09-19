/**
 * Cross-platform vocabulary for interactive surfaces (buttons, links, toggles,
 * tabs, menu items, …).
 *
 * These are the platform-agnostic *semantic* axes of Onyx's interactive color
 * system — the same on web (Opal `Interactive.Stateless`) and mobile. Each
 * platform extends this with its own event wiring + styling; the variant →
 * className color matrix is deliberately NOT shared (it stays per-platform).
 *
 * `interaction` (rest/hover/active) is intentionally absent: its value set
 * diverges — web has `hover`, touch does not — so each platform declares its own.
 */

/** Visual variant controlling the color palette. */
export type InteractiveVariant = "default" | "action" | "danger";

/** Prominence level controlling background intensity. */
export type InteractiveProminence =
  | "primary"
  | "secondary"
  | "tertiary"
  | "internal";

/**
 * Platform-agnostic semantic core every interactive surface shares. Platforms
 * extend this (web adds DOM/event props + `interaction`; mobile adds press
 * wiring + sizing) and implement the color matrix themselves.
 */
export interface InteractiveContract {
  /** @default "default" */
  variant?: InteractiveVariant;
  /** @default "primary" */
  prominence?: InteractiveProminence;
  /** Applies variant-specific disabled colors and suppresses interaction. */
  disabled?: boolean;
}
