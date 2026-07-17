// Sidebar layout breakpoints — used by useScreenSize to determine mobile/small/desktop rendering.
// Named min-width style (matches Tailwind/Bootstrap): each constant is the width at which that
// tier begins. Below SMALL is mobile; [SMALL, MEDIUM) is small; MEDIUM and up is desktop.
// The sidebar docks at or above MEDIUM_BREAKPOINT_PX and overlays below it.
// Canonical source; the app's lib/constants.ts re-imports these.
export const SMALL_BREAKPOINT_PX = 724;
export const MEDIUM_BREAKPOINT_PX = 912;
