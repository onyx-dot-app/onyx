/**
 * Every app-wide chat shortcut, in `useHotkey` syntax. `toggleSidebar` is
 * bound by Opal's `SidebarLayouts.Root`; it is listed here so the shortcut
 * list stays complete.
 */
export const CHAT_SHORTCUTS = {
  newChat: "mod+shift+o",
  toggleSidebar: "mod+e",
  openModelPicker: "mod+/",
  previousChat: "alt+ArrowUp",
  nextChat: "alt+ArrowDown",
} as const;

/** ⌘⌥1–9 on macOS, Ctrl+Alt+1–9 elsewhere: ⌘1–9 and Alt+1–9 switch browser tabs. */
export const JUMP_TO_CHAT_SHORTCUTS: readonly string[] = Array.from(
  { length: 9 },
  (_, index) => `mod+alt+${index + 1}`
);
