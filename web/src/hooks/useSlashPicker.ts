import { useCallback, useRef, useState, type RefObject } from "react";
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
  inputRef: RefObject<BaseInputBarHandle | null>;
  /** Called when the user picks an entry; the caller adds it (e.g. a chip). */
  onSelect: (entry: PickerEntry) => void;
}

export interface UseSlashPickerResult {
  open: boolean;
  query: string;
  anchorRect: DOMRect | null;
  onSelect: (entry: PickerEntry) => void;
  onClose: () => void;
  reset: () => void;
  onInput: () => void;
  onSelectionChange: () => void;
}

/** Drives the `/`-triggered entry picker over a BaseInputBar. */
export default function useSlashPicker({
  inputRef,
  onSelect,
}: UseSlashPickerOptions): UseSlashPickerResult {
  const [session, setSession] = useState<PickerSession>(INITIAL_PICKER_SESSION);
  // Mirror into a ref so the returned handlers keep a stable identity.
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

  // Re-sync (or close) the picker after the caret moves (arrow keys, click).
  const onSelectionChange = useCallback(() => {
    const current = sessionRef.current;
    if (!current.open) return;
    const text = inputRef.current?.getTextBeforeCursor() ?? null;
    const next = reduceOnSelection(current, text);
    if (next.open) setAnchorRect(inputRef.current?.getCaretRect() ?? null);
    setSession(next);
  }, [inputRef]);

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
  };
}
