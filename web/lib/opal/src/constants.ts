// Screen-size breakpoints — used by useScreenSize to determine the current tier.
// Named min-width style (matches Tailwind sm/md/lg): each constant is the width at
// which that tier begins. Tiers: mobile < SMALL ≤ small < MEDIUM ≤ medium < LARGE ≤ desktop.
// The sidebar docks at or above MEDIUM_BREAKPOINT_PX and overlays below it; container-
// relative modal centering engages at or above LARGE_BREAKPOINT_PX.
// Canonical source; the app's lib/constants.ts re-imports these.
export const SMALL_BREAKPOINT_PX = 724; // Tailwind `sm`
export const MEDIUM_BREAKPOINT_PX = 912; // Tailwind `md`
export const LARGE_BREAKPOINT_PX = 1232; // Tailwind `lg`
