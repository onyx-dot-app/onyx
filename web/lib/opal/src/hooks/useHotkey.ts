"use client";

import { useEffect, useRef } from "react";

export interface UseHotkeyOptions {
  /** Whether the hotkey is bound. @default true */
  enabled?: boolean;
  /**
   * Fire even while the user types in a field (an input, textarea, select or
   * contenteditable element). @default false
   */
  whileTyping?: boolean;
}

interface ParsedHotkey {
  key: string;
  mod: boolean;
  ctrl: boolean;
  meta: boolean;
  alt: boolean;
  /** Checked only when the hotkey names it, since keys like `?` need it. */
  shift: boolean | undefined;
}

function parseHotkey(hotkey: string): ParsedHotkey {
  const parts = hotkey.split("+");
  // A trailing "+" is the plus key itself.
  const key = hotkey.endsWith("++") ? "+" : (parts.pop() ?? "");
  const modifiers = new Set(parts.map((part) => part.toLowerCase()));
  return {
    key,
    mod: modifiers.has("mod"),
    ctrl: modifiers.has("ctrl"),
    meta: modifiers.has("meta"),
    alt: modifiers.has("alt"),
    shift: modifiers.has("shift") ? true : undefined,
  };
}

function isMac(): boolean {
  return /mac|iphone|ipad/i.test(navigator.userAgent);
}

function matches(event: KeyboardEvent, hotkey: ParsedHotkey): boolean {
  if (event.key.toLowerCase() !== hotkey.key.toLowerCase()) return false;
  const mac = isMac();
  const wantMeta = hotkey.meta || (hotkey.mod && mac);
  const wantCtrl = hotkey.ctrl || (hotkey.mod && !mac);
  if (event.metaKey !== wantMeta || event.ctrlKey !== wantCtrl) return false;
  if (event.altKey !== hotkey.alt) return false;
  if (hotkey.shift !== undefined && event.shiftKey !== hotkey.shift) {
    return false;
  }
  return true;
}

/** Whether a key event lands where the user types text. */
export function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      target.closest("input, textarea, select") !== null)
  );
}

/**
 * Binds a page-wide keyboard shortcut for as long as the calling component
 * is mounted.
 *
 * `hotkey` is a key name as in `KeyboardEvent.key` (`"/"`, `"Escape"`,
 * `"k"`), optionally prefixed with modifiers joined by `+`: `mod` (⌘ on
 * macOS, Ctrl elsewhere), `ctrl`, `meta`, `alt` and `shift`. Modifiers not
 * named must be up, except Shift, which is checked only when named.
 *
 * A matching key calls `handler` and prevents the browser default. The
 * hotkey stands aside when a component already handled the key (its event
 * is default-prevented) and, unless `whileTyping` is set, while the user
 * types in a field.
 *
 * @example
 * ```tsx
 * // "/" focuses the search field.
 * useHotkey("/", () => searchRef.current?.focus());
 *
 * // ⌘E / Ctrl+E toggles the sidebar.
 * useHotkey("mod+e", () => setFolded((folded) => !folded));
 * ```
 */
export default function useHotkey(
  hotkey: string,
  handler: (event: KeyboardEvent) => void,
  { enabled = true, whileTyping = false }: UseHotkeyOptions = {}
): void {
  // The latest handler, so an inline callback does not rebind the listener.
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  });

  useEffect(() => {
    if (!enabled) return;
    const parsed = parseHotkey(hotkey);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented) return;
      if (!whileTyping && isTypingTarget(event.target)) return;
      if (!matches(event, parsed)) return;
      event.preventDefault();
      handlerRef.current(event);
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [hotkey, enabled, whileTyping]);
}
