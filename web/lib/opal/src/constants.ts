// Screen-size breakpoints — used by useScreenSize to determine the current tier.
// Named min-width style (matches Tailwind sm/md): each constant is the width at which
// that tier begins. Tiers: mobile < SMALL ≤ small < MEDIUM ≤ desktop.
// The sidebar docks at or above MEDIUM_BREAKPOINT_PX and overlays below it.
// Canonical source; the app's lib/constants.ts re-imports these.
export const SMALL_BREAKPOINT_PX = 724; // Tailwind `sm`
export const MEDIUM_BREAKPOINT_PX = 912; // Tailwind `md`
