"use client";

import { useCallback, useRef, type KeyboardEvent } from "react";
import useHotkey from "@opal/hooks/useHotkey";

export interface UseSearchFieldOptions {
  /** The field's current text. */
  value: string;
  /** Sets the field's text. */
  onChange: (value: string) => void;
  /** Focus the field when it mounts. @default true */
  focusOnMount?: boolean;
  /** The hotkey that returns focus to the field; `null` binds none. @default "/" */
  hotkey?: string | null;
}

export interface UseSearchFieldReturn {
  /** Put on the search input. */
  ref: (element: HTMLInputElement | null) => void;
  /**
   * Moves focus to the field, with the caret at the end. A value passed in
   * replaces the current text first.
   */
  focus: (nextValue?: string) => void;
  /**
   * Put on the input's `onKeyDown`. Escape clears the text, then, on an empty
   * field, leaves it. Keys that build an IME composition are left alone.
   */
  onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
}

/**
 * A page's main search field: focused on arrival, cleared and then left with
 * Escape, and focused again with a hotkey ("/" by default).
 *
 * @example
 * ```tsx
 * const search = useSearchField({ value: query, onChange: setQuery });
 * <InputTypeIn
 *   ref={search.ref}
 *   value={query}
 *   onChange={(event) => setQuery(event.target.value)}
 *   onKeyDown={search.onKeyDown}
 * />
 * ```
 */
export default function useSearchField({
  value,
  onChange,
  focusOnMount = true,
  hotkey = "/",
}: UseSearchFieldOptions): UseSearchFieldReturn {
  const inputRef = useRef<HTMLInputElement | null>(null);

  const ref = useCallback(
    (element: HTMLInputElement | null) => {
      inputRef.current = element;
      if (focusOnMount) element?.focus();
    },
    [focusOnMount]
  );

  const focus = useCallback(
    (nextValue?: string) => {
      const input = inputRef.current;
      if (!input) return;
      if (nextValue !== undefined) onChange(nextValue);
      input.focus();
      // After React writes a new value.
      requestAnimationFrame(() => {
        const end = input.value.length;
        input.setSelectionRange(end, end);
      });
    },
    [onChange]
  );

  useHotkey(hotkey ?? "", () => focus(), { enabled: hotkey !== null });

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      // Keys that build or cancel an IME composition belong to the IME.
      if (event.nativeEvent.isComposing) return;
      if (event.key !== "Escape") return;
      event.preventDefault();
      if (value !== "") onChange("");
      else event.currentTarget.blur();
    },
    [value, onChange]
  );

  return { ref, focus, onKeyDown };
}
