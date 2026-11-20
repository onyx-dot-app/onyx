// macOS uses Command for app shortcuts; Windows and Linux use Control.
export const IS_MAC: boolean = navigator.userAgent.includes("Mac");

interface ModifierState {
  metaKey: boolean;
  ctrlKey: boolean;
}

export function hasPrimaryModifier(event: ModifierState): boolean {
  return IS_MAC ? event.metaKey : event.ctrlKey;
}

// The label of the primary modifier with `key`: "⌘N" on macOS, "Ctrl+N" elsewhere.
// "Shift+" in `key` shows as ⇧ on macOS.
export function primaryShortcut(key: string): string {
  if (!IS_MAC) return `Ctrl+${key}`;
  if (key === "Enter") return "⌘↵";
  return `⌘${key.replace("Shift+", "⇧")}`;
}
