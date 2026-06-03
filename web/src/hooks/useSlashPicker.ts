import {
  useCallback,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from "react";
import type { BaseInputBarHandle } from "@/sections/input/BaseInputBar";
import type { PickerEntry } from "@/lib/skills/picker";
import {
  INITIAL_PICKER_SESSION,
  reduceOnDismiss,
  reduceOnInput,
  reduceOnSelection,
  type PickerSession,
} from "@/lib/skills/pickerSession";

interface UseSlashPickerOptions {
  /** Handle to the input the picker reads the caret/token from. */
  inputRef: RefObject<BaseInputBarHandle | null>;
  /** Called when the user picks an entry; the caller adds it (e.g. a chip). */
  onSelect: (entry: PickerEntry) => void;
}

export interface UseSlashPickerResult {
  /** Picker popover state. */
  open: boolean;
  query: string;
  anchorRect: DOMRect | null;
  /** Wire to the picker popover. */
  onSelect: (entry: PickerEntry) => void;
  onClose: () => void;
  /** Force the session closed (e.g. on input-bar reset). */
  reset: () => void;
  /** Wire to BaseInputBar. */
  onInput: () => void;
  onSelectionChange: () => void;
  onBeforeKeyDown: (event: KeyboardEvent<HTMLDivElement>) => boolean;
}

/**
 * Drives the `/`-triggered entry picker over a BaseInputBar. Owns the picker
 * session + anchor and exposes handlers to wire into the input bar and popover.
 * Domain-agnostic: it surfaces the selected `PickerEntry` and lets the caller
 * decide what to do with it.
 */
export default function useSlashPicker({
  inputRef,
  onSelect,
}: UseSlashPickerOptions): UseSlashPickerResult {
  const [session, setSession] = useState<PickerSession>(INITIAL_PICKER_SESSION);
  // Mirror `session` into a ref so the handlers keep a stable identity across
  // query changes (BaseInputBar is memoized).
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

  const reset = useCallback(() => setSession(INITIAL_PICKER_SESSION), []);
  const onClose = useCallback(() => setSession(reduceOnDismiss), []);

  const onInput = useCallback(() => {
    const text = inputRef.current?.getTextBeforeCursor() ?? null;
    const next = reduceOnInput(sessionRef.current, text);
    if (next.open) setAnchorRect(inputRef.current?.getCaretRect() ?? null);
    setSession(next);
  }, [inputRef]);

  // Re-evaluate the trigger after the caret moves (arrow keys, click). Keeps
  // the query in sync or closes the picker when the caret leaves the token.
  const onSelectionChange = useCallback(() => {
    const current = sessionRef.current;
    if (!current.open) return;
    const text = inputRef.current?.getTextBeforeCursor() ?? null;
    const next = reduceOnSelection(current, text);
    if (next.open) setAnchorRect(inputRef.current?.getCaretRect() ?? null);
    setSession(next);
  }, [inputRef]);

  const onBeforeKeyDown = useCallback(
    (_event: KeyboardEvent<HTMLDivElement>): boolean => {
      onSelectionChange();
      return false;
    },
    [onSelectionChange]
  );

  const handleSelect = useCallback(
    (entry: PickerEntry) => {
      const current = sessionRef.current;
      if (!current.open) return;
      inputRef.current?.deleteBeforeToken(`/${current.query}`);
      onSelect(entry);
      reset();
    },
    [inputRef, onSelect, reset]
  );

  return {
    open: session.open,
    query: session.query,
    anchorRect,
    onSelect: handleSelect,
    onClose,
    reset,
    onInput,
    onSelectionChange,
    onBeforeKeyDown,
  };
}
