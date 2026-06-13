// Shared (non-prop) types for the Sidebar primitive. Mirrors the web Opal
// `Interactive.Stateful` sidebar variants and states.

export type SidebarVariant = "sidebar-heavy" | "sidebar-light";

export type SidebarTabState = "empty" | "selected";

// Layout constants ported from web/lib/opal/src/styles/sizes.css
// (--sidebar-width-expanded: 15rem, --sidebar-width-folded: 3.25rem). On a phone
// the folded rail is unused (folded === off-screen), so only EXPANDED applies.
export const SIDEBAR_WIDTH_EXPANDED = 240;
export const SIDEBAR_WIDTH_FOLDED = 52;

// Slide/backdrop transition duration — matches web's `duration-200`.
export const SIDEBAR_ANIM_MS = 200;
