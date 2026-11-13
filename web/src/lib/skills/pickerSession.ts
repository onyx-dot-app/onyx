/**
 * Pure state machine for the skill-picker session in an input bar.
 *
 * The picker is a typing session keyed on the active trigger character ("/"
 * in Craft, "@" in chat; see `detectPickerTrigger`), not a reflection of the caret.
 * `triggerIndex` tracks that character; `suppressed` hides the picker within the
 * token after Esc; both reset once the trigger is gone. Caret movement never
 * opens the picker — only typing a trigger does.
 *
 * These reducers are pure (no DOM): the host reads the text-before-cursor and
 * the caret rect, then feeds the text in here and applies the result.
 */

import { detectPickerTrigger } from "@/lib/skills/picker";

export interface PickerSession {
  /** Index of the tracked trigger in the input text, or null when no session. */
  triggerIndex: number | null;
  /** Whether the picker is hidden within the tracked token (Esc). */
  suppressed: boolean;
  /** Whether the picker is currently visible. */
  open: boolean;
  /** The query typed after the tracked trigger. */
  query: string;
}

export const INITIAL_PICKER_SESSION: PickerSession = {
  triggerIndex: null,
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
  textBeforeCursor: string | null,
  trigger: string
): PickerSession {
  const match =
    textBeforeCursor === null
      ? null
      : detectPickerTrigger(textBeforeCursor, trigger);

  if (!match) {
    // No active trigger. Keep a dismissed session alive while its trigger
    // character survives (so deleting back into the token doesn't reopen it);
    // fully reset once it is gone, letting a fresh trigger re-arm later.
    const index = state.triggerIndex;
    if (index === null || textBeforeCursor?.[index] !== trigger) {
      return INITIAL_PICKER_SESSION;
    }
    return hidden(state);
  }

  if (match.triggerIndex !== state.triggerIndex) {
    return {
      triggerIndex: match.triggerIndex,
      suppressed: false,
      open: true,
      query: match.query,
    };
  }

  if (state.suppressed) return hidden(state);

  return state.open && state.query === match.query
    ? state
    : { ...state, open: true, query: match.query };
}

/** Caret moved (arrows/click): never opens; closes or syncs the query. */
export function reduceOnSelection(
  state: PickerSession,
  textBeforeCursor: string | null,
  trigger: string
): PickerSession {
  if (!state.open) return state;
  const match =
    textBeforeCursor === null
      ? null
      : detectPickerTrigger(textBeforeCursor, trigger);
  if (!match || match.triggerIndex !== state.triggerIndex) {
    return INITIAL_PICKER_SESSION;
  }
  return state.query === match.query ? state : { ...state, query: match.query };
}

/** Esc / outside-click: hide within the current token until its trigger is gone. */
export function reduceOnDismiss(state: PickerSession): PickerSession {
  return state.open || !state.suppressed
    ? { ...state, suppressed: true, open: false }
    : state;
}
