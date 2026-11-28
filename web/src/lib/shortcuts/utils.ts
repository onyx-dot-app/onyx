/**
 * The chat one step from `currentId` in the sidebar list, or null past either
 * end. From a chat that is not in the list, the step enters it at its near end.
 */
export function adjacentChatId(
  chatIds: readonly string[],
  currentId: string | null,
  step: 1 | -1
): string | null {
  const index = currentId === null ? -1 : chatIds.indexOf(currentId);
  if (index === -1) {
    return (step === 1 ? chatIds[0] : chatIds[chatIds.length - 1]) ?? null;
  }
  return chatIds[index + step] ?? null;
}

export interface KeyNames {
  ctrl: string;
  alt: string;
  shift: string;
}

const MODIFIER_ORDER = ["ctrl", "alt", "shift", "meta"] as const;
type Modifier = (typeof MODIFIER_ORDER)[number];

const MAC_MODIFIER_SYMBOLS: Record<Modifier, string> = {
  ctrl: "⌃",
  alt: "⌥",
  shift: "⇧",
  meta: "⌘",
};

const KEY_SYMBOLS: Record<string, string> = {
  ArrowUp: "↑",
  ArrowDown: "↓",
  ArrowLeft: "←",
  ArrowRight: "→",
  Enter: "↵",
};

/**
 * A `useHotkey` string as the user presses it: `⇧⌘O` on macOS, `Ctrl+Shift+O`
 * elsewhere, with modifiers in the platform's usual order.
 */
export function formatHotkey(
  hotkey: string,
  isMac: boolean,
  keyNames: KeyNames
): string {
  const parts = hotkey.split("+");
  const key = parts.pop() ?? "";
  const pressed = new Set(
    parts.map((part) => {
      const modifier = part.toLowerCase();
      if (modifier === "mod") return isMac ? "meta" : "ctrl";
      return modifier;
    })
  );
  const modifiers = MODIFIER_ORDER.filter((modifier) => pressed.has(modifier));
  const keyLabel = KEY_SYMBOLS[key] ?? key.toUpperCase();

  if (isMac) {
    return (
      modifiers.map((modifier) => MAC_MODIFIER_SYMBOLS[modifier]).join("") +
      keyLabel
    );
  }
  const names: Record<Modifier, string> = { ...keyNames, meta: "Meta" };
  return [...modifiers.map((modifier) => names[modifier]), keyLabel].join("+");
}

/**
 * Whether a modal layer (a dialog such as the command palette) is open.
 * Radix blocks pointer events on `<body>` for each modal layer, and only for
 * modal layers, so a popover such as the model picker does not count.
 */
export function isModalOpen(): boolean {
  return document.body.style.pointerEvents === "none";
}

/** Opens the chat model picker on its first model, or closes it when open. */
export function toggleModelPicker(): void {
  const openPicker = document.querySelector<HTMLElement>(
    "button[data-model-picker-open], [data-model-picker-open] button"
  );
  const firstModel = document.querySelector<HTMLElement>(
    "[data-model-picker-pill] button"
  );
  (openPicker ?? firstModel)?.click();
}

let recentChatShortcutTarget: string | null = null;

export function markRecentChatShortcutTarget(chatId: string) {
  recentChatShortcutTarget = chatId;
}

export function takeRecentChatShortcutTarget(chatId: string | null): boolean {
  const keepFocus = chatId !== null && recentChatShortcutTarget === chatId;
  recentChatShortcutTarget = null;
  return keepFocus;
}
