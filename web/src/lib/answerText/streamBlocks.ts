// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

// Definitions, footnotes, raw HTML and container directives can tie blocks together,
// also inside block quotes and list items. A line that opens a label without closing
// it may start a definition whose label spans lines. A label may hold escaped brackets.
const DOCUMENT_WIDE_SYNTAX =
  /^(?:[ \t]*(?:>|[-*+](?=[ \t])|\d{1,9}[.)](?=[ \t])))*[ \t]*(?:\[(?:\\.|[^\]\\\n])+\]:|\[(?:\\.|[^\]\\\n])*\\?$|<[A-Za-z!?/]|:::)|\[\^/m;
// A backtick fence's info string cannot contain a backtick, so "```a``` is inline" is a code span.
const FENCE_PATTERN = /^ {0,3}(`{3,}(?![^`\n]*`)|~{3,})/;
// After a blank line these still continue the previous block: a list item or indented content.
const CONTINUATION_PATTERN = /^(?:[ \t]|(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$))/;

/**
 * The fence of display math that `line` opens, or null. As in remark-math, a
 * fence is two or more dollar signs, and the text after it has no dollar
 * sign; otherwise the line is a paragraph with inline math.
 */
function mathFence(line: string): string | null {
  return /^(\${2,})[^$]*$/.exec(line.trim())?.[1] ?? null;
}

/** As in remark-math, only a line of as many or more dollar signs closes. */
function closesMath(line: string, fence: string): boolean {
  const trimmed = line.trim();
  return /^\$+$/.test(trimmed) && trimmed.length >= fence.length;
}

/**
 * Whether `text` ends inside a fenced code block that is not closed yet. A
 * fence in a block quote or list item also ends with its container: at a
 * line with fewer quote markers, or with text left of the fence.
 */
export function endsInOpenCodeFence(text: string): boolean {
  let fence: { marker: string; depth: number; indent: number } | null = null;
  for (const line of text.split("\n")) {
    const quotes = /^(?:[ \t]*>)*/.exec(line)?.[0] ?? "";
    const depth = quotes.split(">").length - 1;
    const rest = line.slice(quotes.length);
    if (fence !== null) {
      if (rest.trim() === "") continue;
      const left = rest.slice(0, fence.indent);
      if (depth >= fence.depth && !/\S/.test(left)) {
        const closing = rest.trim();
        if (
          /^(`+|~+)$/.test(closing) &&
          closing[0] === fence.marker[0] &&
          closing.length >= fence.marker.length
        )
          fence = null;
        continue;
      }
      fence = null;
    }
    const opener =
      /^([ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)*)(`{3,}(?![^`\n]*`)|~{3,})/.exec(
        rest
      );
    if (opener?.[2])
      fence = { marker: opener[2], depth, indent: opener[1]?.length ?? 0 };
  }
  return fence !== null;
}

/**
 * Cuts Markdown at blank lines that close every open block, so each piece
 * renders exactly as it would inside the whole text. Returns null when the
 * text uses syntax that spans blocks, such as link definitions.
 */
export function splitMarkdownBlocks(text: string): string[] | null {
  if (
    text.startsWith("﻿") ||
    text.includes("\r") ||
    DOCUMENT_WIDE_SYNTAX.test(text)
  )
    return null;
  const blocks: string[] = [];
  let blockStart = 0;
  let lineStart = 0;
  let fence: string | null = null;
  let math: string | null = null;
  // The indent of the open fence or math block.
  let openIndent = 0;
  let afterBlankLine = false;
  for (const line of text.split("\n")) {
    const opener = FENCE_PATTERN.exec(line)?.[1];
    if (fence !== null || math !== null) {
      // A line left of an indented block may end the list item holding it, which isn't tracked.
      if (/\S/.test(line.slice(0, openIndent))) break;
      if (math !== null) {
        if (closesMath(line, math)) math = null;
      } else if (
        fence !== null &&
        opener &&
        opener[0] === fence[0] &&
        opener.length >= fence.length &&
        line.trim() === opener
      ) {
        fence = null;
      }
    } else if (line.trim() === "") {
      afterBlankLine = true;
    } else {
      if (
        afterBlankLine &&
        lineStart > blockStart &&
        !CONTINUATION_PATTERN.test(line)
      ) {
        blocks.push(text.slice(blockStart, lineStart));
        blockStart = lineStart;
      }
      afterBlankLine = false;
      fence = opener ?? null;
      math = opener ? null : mathFence(line);
      if (opener) openIndent = line.indexOf(opener);
      else if (math !== null) openIndent = line.indexOf(math);
    }
    lineStart += line.length + 1;
  }
  blocks.push(text.slice(blockStart));
  return blocks;
}
