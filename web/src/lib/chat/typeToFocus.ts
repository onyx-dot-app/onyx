"use client";

import type {
  ClipboardEvent as ReactClipboardEvent,
  KeyboardEvent as ReactKeyboardEvent,
  RefObject,
} from "react";
import { isTypingTarget } from "@opal/hooks";

const OPEN_LAYER_SELECTOR =
  '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]';

const SPACE_ACTIVATES_SELECTOR =
  'button, a[href], summary, [role="button"], [role="link"], [role="checkbox"], [role="radio"], [role="switch"], [role="tab"], [role="option"], [role="menuitem"]';

function belongsToPage(target: EventTarget | null): boolean {
  if (isTypingTarget(target)) return false;
  return document.querySelector(OPEN_LAYER_SELECTOR) === null;
}

/** Whether a key press outside any field should type into the chat input. */
export function shouldTypeIntoComposer(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.isComposing) return false;
  if (event.ctrlKey || event.metaKey || event.altKey) return false;
  if (event.key.length !== 1) return false;
  if (
    event.key === " " &&
    event.target instanceof Element &&
    event.target.closest(SPACE_ACTIVATES_SELECTOR) !== null
  ) {
    return false;
  }
  return belongsToPage(event.target);
}

export interface TypeToFocusTarget {
  focus: () => void;
  paste: (data: DataTransfer) => void;
}

export interface TypeToFocusHandlers {
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  onPaste: (event: ReactClipboardEvent<HTMLElement>) => void;
}

/**
 * Event props for the chat page's focusable root. Typing and pasting that
 * land inside the page but outside any field go to the chat input. A key
 * press only moves focus, so the browser types the character there.
 */
export function typeToFocusHandlers(
  composerRef: RefObject<TypeToFocusTarget | null>
): TypeToFocusHandlers {
  return {
    onKeyDown: (event) => {
      if (shouldTypeIntoComposer(event.nativeEvent)) {
        composerRef.current?.focus();
      }
    },
    onPaste: (event) => {
      const composer = composerRef.current;
      if (!composer || event.defaultPrevented) return;
      if (!belongsToPage(event.target)) return;
      event.preventDefault();
      composer.paste(event.clipboardData);
    },
  };
}
