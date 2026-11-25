// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

// Definitions, footnotes, raw HTML and container directives can tie blocks together.
const DOCUMENT_WIDE_SYNTAX = /^ {0,3}(?:\[[^\]\n]+\]:|<[A-Za-z!?/]|:::)|\[\^/m;
// A backtick fence's info string cannot contain a backtick, so "```a``` is inline" is a code span.
const FENCE_PATTERN = /^ {0,3}(`{3,}(?![^`\n]*`)|~{3,})/;
// After a blank line these still continue the previous block: a list item or indented content.
const CONTINUATION_PATTERN = /^(?:[ \t]|(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$))/;

/** Whether `line` opens display math that a later line closes. */
function opensMath(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.startsWith("$$") && !trimmed.slice(2).includes("$$");
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
  let inMath = false;
  // The indent of the open fence or math block.
  let openIndent = 0;
  let afterBlankLine = false;
  for (const line of text.split("\n")) {
    const opener = FENCE_PATTERN.exec(line)?.[1];
    if (fence !== null || inMath) {
      // A line left of an indented block may end the list item holding it, which isn't tracked.
      if (/\S/.test(line.slice(0, openIndent))) break;
      if (inMath) {
        if (line.trim().endsWith("$$")) inMath = false;
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
      inMath = !opener && opensMath(line);
      if (opener) openIndent = line.indexOf(opener);
      else if (inMath) openIndent = line.indexOf("$$");
    }
    lineStart += line.length + 1;
  }
  blocks.push(text.slice(blockStart));
  return blocks;
}
