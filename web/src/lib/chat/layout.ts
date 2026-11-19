import { cn } from "@opal/utils";

// The chat column's width comes from the page (`--app-chat-column-width`, set
// by AppPage for its compact and full-width modes). A page that does not set
// it, such as Craft, gets the compact reading width. The cap only applies at
// md and up — below that the window is too narrow for it to matter, so chat
// is always full width (and the top-bar toggle is hidden).
const CHAT_COLUMN_MAX_WIDTH =
  "md:max-w-[var(--app-chat-column-width,var(--width-chat-message-max))]";

/** Animates the full-width toggle; every surface it widens uses this. */
export const FULL_WIDTH_TRANSITION =
  "transition-[max-width] duration-300 ease-in-out motion-reduce:transition-none";

/** The reading-width cap on a conversation's rows, in chat and Craft. */
export const CHAT_COLUMN_WIDTH = cn(
  CHAT_COLUMN_MAX_WIDTH,
  FULL_WIDTH_TRANSITION
);

/** A conversation row: full width, centred, capped at the column width. */
export const CHAT_COLUMN_ROW = cn("w-full self-center", CHAT_COLUMN_WIDTH);

/** The side gutter around a conversation; it matches the input bar's. */
export const CHAT_GUTTER = "px-2 sm:px-4";
