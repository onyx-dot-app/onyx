/**
 * Pure state machine for the skill-picker session in an input bar.
 *
 * The picker is a typing session keyed on the active trigger character ("/"
 * in Craft, "@" in chat; see `detectPickerTrigger`), not a reflection of the caret.
 * `triggerIndex` tracks that character; `suppressed` hides the picker within the
 * token after Esc; both reset once the trigger is gone. Only input opens the
 * picker or changes its query; the host ends the session when the caret moves.
 * An open session always has entries to show: a word that matches nothing ends
 * it.
 *
 * These reducers are pure (no DOM): the host reads the text around the caret
 * and the caret rect, then feeds the text in here and applies the result.
 */

import type { CaretText } from "@/lib/contentEditable";
import {
  detectPickerTrigger,
  flattenSections,
  type PickerSections,
} from "@/lib/skills/picker";

export interface PickerSession {
  /** Index of the tracked trigger in the input text, or null when no session. */
  triggerIndex: number | null;
  /** Whether the picker is hidden within the tracked token (Esc). */
  suppressed: boolean;
  /** Whether the picker is currently visible. */
  open: boolean;
  /** The whole word after the tracked trigger. */
  query: string;
  /** The text a pick replaces: the trigger and query, split at the caret. */
  token: CaretText;
  /** The entries that match `query`. */
  sections: PickerSections;
}

export const INITIAL_PICKER_SESSION: PickerSession = {
  triggerIndex: null,
  suppressed: false,
  open: false,
  query: "",
  token: { before: "", after: "" },
  sections: { skills: [], apps: [], mcpServers: [] },
};

function hidden(state: PickerSession): PickerSession {
  return state.open ? { ...state, open: false } : state;
}

/** Input: the only event that can open the picker. */
export function reduceOnInput(
  state: PickerSession,
  text: CaretText | null,
  trigger: string,
  search: (query: string) => PickerSections
): PickerSession {
  const match = text === null ? null : detectPickerTrigger(text, trigger);

  if (!match) {
    // No active trigger. Keep a dismissed session alive while its trigger
    // character survives (so deleting back into the token doesn't reopen it);
    // fully reset once it is gone, letting a fresh trigger re-arm later.
    const index = state.triggerIndex;
    if (index === null || text?.before[index] !== trigger) {
      return INITIAL_PICKER_SESSION;
    }
    return hidden(state);
  }

  if (match.triggerIndex === state.triggerIndex && state.suppressed) {
    return hidden(state);
  }

  const sections = search(match.query);
  if (flattenSections(sections).length === 0) return INITIAL_PICKER_SESSION;

  return {
    triggerIndex: match.triggerIndex,
    suppressed: false,
    open: true,
    query: match.query,
    token: match.token,
    sections,
  };
}

/** Esc: hide within the current token until its trigger is gone. */
export function reduceOnEscape(state: PickerSession): PickerSession {
  return state.open || !state.suppressed
    ? { ...state, suppressed: true, open: false }
    : state;
}
