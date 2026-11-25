// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).
import type { CSSProperties } from "react";
import { ANSI_ESCAPE } from "@/lib/sandbox/ansi";

export type TerminalSpanStyle = Pick<
  CSSProperties,
  | "color"
  | "backgroundColor"
  | "fontWeight"
  | "opacity"
  | "fontStyle"
  | "textDecorationLine"
>;

export interface TerminalSpan {
  text: string;
  style: TerminalSpanStyle | null;
}

interface Pen {
  fg?: string;
  bg?: string;
  bold: boolean;
  dim: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
  inverse: boolean;
}

const BASE_COLORS = 16;
const SGR = /^\u001b\[([0-9;:]*)m$/u; // oxlint-disable-line no-control-regex -- matches the SGR escape
// The cap bounds DOM nodes; output past it shows as one plain span.
const MAX_SPANS = 2000;

function baseColor(index: number): string {
  return `var(--opal-ansi-${index})`;
}

function xtermColor(index: number): string | undefined {
  if (index < 0 || index > 255) return undefined;
  if (index < BASE_COLORS) return baseColor(index);
  if (index >= 232) {
    const level = 8 + (index - 232) * 10;
    return `rgb(${level},${level},${level})`;
  }
  const cube = index - 16;
  const channel = (value: number) => (value === 0 ? 0 : 55 + value * 40);
  return `rgb(${channel(Math.floor(cube / 36))},${channel(Math.floor(cube / 6) % 6)},${channel(cube % 6)})`;
}

/** Reads an extended color (`38;5;n` or `38;2;r;g;b`) at `i`; returns it and the next index. */
function extendedColor(
  codes: number[],
  i: number
): [string | undefined, number] {
  if (codes[i + 1] === 5) return [xtermColor(codes[i + 2] ?? -1), i + 3];
  if (codes[i + 1] === 2) {
    const [r, g, b] = [codes[i + 2], codes[i + 3], codes[i + 4]];
    const valid = [r, g, b].every((v) => v !== undefined && v >= 0 && v <= 255);
    return [valid ? `rgb(${r},${g},${b})` : undefined, i + 5];
  }
  return [undefined, i + 1];
}

function newPen(): Pen {
  return {
    bold: false,
    dim: false,
    italic: false,
    underline: false,
    strike: false,
    inverse: false,
  };
}

function applySgr(pen: Pen, params: string): Pen {
  const codes = params === "" ? [0] : params.split(/[;:]/).map(Number);
  let next = { ...pen };
  for (let i = 0; i < codes.length; i++) {
    const code = codes[i] ?? 0;
    if (code === 0) next = newPen();
    else if (code === 1) next.bold = true;
    else if (code === 2) next.dim = true;
    else if (code === 3) next.italic = true;
    else if (code === 4) next.underline = true;
    else if (code === 7) next.inverse = true;
    else if (code === 9) next.strike = true;
    else if (code === 22) {
      next.bold = false;
      next.dim = false;
    } else if (code === 23) next.italic = false;
    else if (code === 24) next.underline = false;
    else if (code === 27) next.inverse = false;
    else if (code === 29) next.strike = false;
    else if (code >= 30 && code <= 37) next.fg = baseColor(code - 30);
    else if (code >= 90 && code <= 97) next.fg = baseColor(code - 90 + 8);
    else if (code >= 40 && code <= 47) next.bg = baseColor(code - 40);
    else if (code >= 100 && code <= 107) next.bg = baseColor(code - 100 + 8);
    else if (code === 39) next.fg = undefined;
    else if (code === 49) next.bg = undefined;
    else if (code === 38 || code === 48) {
      const [color, after] = extendedColor(codes, i);
      if (code === 38) next.fg = color;
      else next.bg = color;
      i = after - 1;
    }
  }
  return next;
}

function penStyle(pen: Pen): TerminalSpanStyle | null {
  let color = pen.fg;
  let backgroundColor = pen.bg;
  if (pen.inverse) {
    [color, backgroundColor] = [backgroundColor, color ?? baseColor(7)];
  }
  const decoration =
    pen.underline && pen.strike
      ? "underline line-through"
      : pen.underline
        ? "underline"
        : pen.strike
          ? "line-through"
          : undefined;
  const style: TerminalSpanStyle = {
    ...(color && { color }),
    ...(backgroundColor && { backgroundColor }),
    ...(pen.bold && { fontWeight: "600" as const }),
    ...(pen.dim && { opacity: 0.65 }),
    ...(pen.italic && { fontStyle: "italic" as const }),
    ...(decoration && { textDecorationLine: decoration }),
  };
  return Object.keys(style).length > 0 ? style : null;
}

/**
 * Splits terminal output into styled spans. The 16 base colors are
 * `var(--opal-ansi-N)`, so they follow the theme inside a `CodePanel`.
 * Escapes other than SGR (cursor moves, titles, links) are dropped.
 */
export function terminalSpans(text: string): TerminalSpan[] {
  if (!text.includes("\u001b")) return [{ text, style: null }];
  const spans: TerminalSpan[] = [];
  let pen = newPen();
  let style = penStyle(pen);
  let cursor = 0;
  const push = (chunk: string) => {
    if (chunk) spans.push({ text: chunk, style });
  };
  for (const match of text.matchAll(ANSI_ESCAPE)) {
    push(text.slice(cursor, match.index));
    cursor = match.index + match[0].length;
    const sgr = SGR.exec(match[0]);
    if (sgr) {
      pen = applySgr(pen, sgr[1] ?? "");
      style = penStyle(pen);
    }
    if (spans.length >= MAX_SPANS) break;
  }
  if (cursor < text.length) {
    const rest = text.slice(cursor);
    if (spans.length >= MAX_SPANS) {
      spans.push({ text: rest.replace(ANSI_ESCAPE, ""), style: null });
    } else {
      push(rest);
    }
  }
  return spans;
}
