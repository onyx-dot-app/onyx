/**
 * Pure state machine for the `/` skill-picker session in the chat input.
 *
 * The picker is a typing session keyed on the active "/" character, not a
 * reflection of the caret. `slashIndex` tracks that "/"; `suppressed` hides the
 * picker within the token after Esc; both reset once the slash is gone. Caret
 * movement never opens the picker — only typing a slash trigger does.
 *
 * These reducers are pure (no DOM): the host reads the text-before-cursor and
 * the caret rect, then feeds the text in here and applies the result.
 */

import { detectSlashTrigger } from "@/lib/skills/picker";

export interface PickerSession {
  /** Index of the tracked "/" in the input text, or null when no session. */
  slashIndex: number | null;
  /** Whether the picker is hidden within the tracked token (Esc). */
  suppressed: boolean;
  /** Whether the picker is currently visible. */
  open: boolean;
  /** The query typed after the tracked "/". */
  query: string;
}

export const INITIAL_PICKER_SESSION: PickerSession = {
  slashIndex: null,
  suppressed: false,
  open: false,
  query: "",
};

function hidden(state: PickerSession): PickerSession {
  return state.open ? { ...state, open: false } : state;
}

/** Typing: the only event that can open the picker. */
export function reduceOnInput(
  state: PickerSession,
  textBeforeCursor: string | null
): PickerSession {
  const trigger =
    textBeforeCursor === null ? null : detectSlashTrigger(textBeforeCursor);

  if (!trigger) {
    // No active trigger. Keep a dismissed session alive while its slash
    // survives (so deleting back into the token doesn't reopen it); fully
    // reset once that slash is gone, letting a fresh "/" re-arm later.
    const slash = state.slashIndex;
    if (slash === null || textBeforeCursor?.[slash] !== "/") {
      return INITIAL_PICKER_SESSION;
    }
    return hidden(state);
  }

  if (trigger.slashIndex !== state.slashIndex) {
    return {
      slashIndex: trigger.slashIndex,
      suppressed: false,
      open: true,
      query: trigger.query,
    };
  }

  if (state.suppressed) return hidden(state);

  return state.open && state.query === trigger.query
    ? state
    : { ...state, open: true, query: trigger.query };
}

/** Caret moved (arrows/click): never opens; closes or syncs the query. */
export function reduceOnSelection(
  state: PickerSession,
  textBeforeCursor: string | null
): PickerSession {
  if (!state.open) return state;
  const trigger =
    textBeforeCursor === null ? null : detectSlashTrigger(textBeforeCursor);
  if (!trigger || trigger.slashIndex !== state.slashIndex) {
    return INITIAL_PICKER_SESSION;
  }
  return state.query === trigger.query
    ? state
    : { ...state, query: trigger.query };
}

/** Esc / outside-click: hide within the current token until its slash is gone. */
export function reduceOnDismiss(state: PickerSession): PickerSession {
  return state.open || !state.suppressed
    ? { ...state, suppressed: true, open: false }
    : state;
}
