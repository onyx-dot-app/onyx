// CSI sequences (colors, cursor moves), OSC sequences (titles, links) that
// end in BEL or ESC \, control strings, and short escapes.
export const ANSI_ESCAPE =
  // oxlint-disable-next-line no-control-regex -- terminal escapes are control characters
  /\u001b(?:\[[0-?]*[ -/]*[@-~]|\][^\u0007\u001b]*(?:\u0007|\u001b\\)|[PX^_][^\u001b]*\u001b\\|[ -/]+[0-~]|[@-Z\\-_])/g;

/** Removes terminal escape sequences, so colored output reads as plain text. */
export function stripAnsi(text: string): string {
  return text.includes("\u001b") ? text.replace(ANSI_ESCAPE, "") : text;
}
