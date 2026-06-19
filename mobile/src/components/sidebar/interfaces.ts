// Shared (non-prop) types for the Sidebar primitive. Mirrors the web Opal
// `Interactive.Stateful` sidebar variants.

export type SidebarVariant = "sidebar-heavy" | "sidebar-light";

// Sidebar column width, ported from web/lib/opal/src/styles/sizes.css
// (--sidebar-width-expanded: 15rem). On a phone the folded rail is unused
// (folded === off-screen), so only the expanded width applies.
export const SIDEBAR_WIDTH_EXPANDED = 240;

// Slide/backdrop transition duration — matches web's `duration-200`.
export const SIDEBAR_ANIM_MS = 200;
