// The chat column's width comes from the page (`--app-chat-column-width`, set
// by AppPage for its compact and full-width modes). A page that does not set
// it gets the compact reading width. The cap only applies at md and up — below
// that the window is too narrow for it to matter, so chat is always full width
// (and the top-bar toggle is hidden).
export const CHAT_COLUMN_MAX_WIDTH =
  "md:max-w-[var(--app-chat-column-width,var(--width-chat-message-max))]";

/** Animates the full-width toggle; every surface it widens uses this. */
export const FULL_WIDTH_TRANSITION =
  "transition-[max-width] duration-300 ease-in-out motion-reduce:transition-none";
