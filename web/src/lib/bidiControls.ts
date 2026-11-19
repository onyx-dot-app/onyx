// Embedding, override and isolate controls, and the directional marks.
const BIDI_CONTROLS = /[\u202A-\u202E\u2066-\u2069\u200E\u200F\u061C]/g;

/** Text without its bidi controls, for display only: a path or label from a
 * sandbox shows its characters in their own order. The caller isolates the
 * text in markup (`dir`), which keeps it from reordering the text around it. */
export function stripBidiControls(text: string): string {
  return text.replace(BIDI_CONTROLS, "");
}
