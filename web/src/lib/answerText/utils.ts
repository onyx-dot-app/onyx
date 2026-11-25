import {
  escapeIncompleteBlockMath,
  preprocessLaTeX,
  replaceFencedCodeBlocks,
} from "@/lib/timeline/chat/message/codeUtils";

// Private-use characters: no math or markdown rewrite matches them.
const PLACEHOLDER_OPEN = "\uE000";
const PLACEHOLDER_CLOSE = "\uE001";
const PLACEHOLDER_REGEX = /\uE000(\d+)\uE001/g;
const LIST_ITEM_REGEX = /^[ \t]*([-*+]|\d{1,9}[.)])[ \t]+\S/;
// A whole line that a kept span (e.g. a fenced block) replaced.
const KEPT_LINE_REGEX = /^\uE000\d+\uE001$/;
const HEADING_REGEX = /^ {0,3}#{1,6}(?:[ \t]|$)/;
const QUOTE_PREFIX_REGEX = /^(?: {0,3}> ?)+/;

/** A line's leading whitespace as columns (a tab counts as 4). */
function indentOf(text: string): number {
  let width = 0;
  for (const char of text) {
    if (char === " ") width += 1;
    else if (char === "\t") width += 4 - (width % 4);
    else break;
  }
  return width;
}

/**
 * Indented code blocks (CommonMark): lines indented 4+ columns past their
 * container (a list item's content, inside any block quotes) that start
 * after a blank line or a heading, never as a paragraph's continuation.
 * The block keeps its original lines, quote markers included.
 */
function replaceIndentedCode(
  content: string,
  replace: (block: string) => string
): string {
  const out: string[] = [];
  let block: string[] | null = null;
  let blockIndent = 0;
  // The content column of the open list item, 0 outside a list.
  let listColumn = 0;
  // Whether the previous line can be continued as a paragraph.
  let inParagraph = false;
  // The block quote depth of the previous line.
  let quoteDepth = 0;
  const flush = () => {
    if (block === null) return;
    // Trailing blank lines belong after the block.
    const trailing: string[] = [];
    while (block.length > 0 && (block[block.length - 1] ?? "").trim() === "") {
      trailing.unshift(block.pop() ?? "");
    }
    out.push(replace(block.join("\n")), ...trailing);
    block = null;
  };
  for (const line of content.split("\n")) {
    const prefix = QUOTE_PREFIX_REGEX.exec(line)?.[0] ?? "";
    const rest = line.slice(prefix.length);
    const blank = rest.trim() === "";
    // A deeper quote opens a new container: no paragraph or list to continue.
    // A shallower line can still continue the quote's paragraph lazily.
    const depth = prefix.split(">").length - 1;
    if (depth > quoteDepth) {
      inParagraph = false;
      listColumn = 0;
    }
    quoteDepth = depth;
    const indent = indentOf(rest);
    if (block !== null) {
      if (blank || indent >= blockIndent) {
        block.push(line);
        continue;
      }
      flush();
    }
    if (blank) {
      out.push(line);
      inParagraph = false;
      continue;
    }
    if (!inParagraph && indent >= listColumn + 4) {
      block = [line];
      blockIndent = listColumn + 4;
      continue;
    }
    // A kept block (a fence's placeholder) is a block of its own.
    if (KEPT_LINE_REGEX.test(rest.trim())) {
      out.push(line);
      inParagraph = false;
      continue;
    }
    // A list item can interrupt a paragraph only as a bullet or an ordered
    // list starting at 1.
    const marker = LIST_ITEM_REGEX.exec(rest);
    const opensList =
      marker !== null &&
      (!inParagraph ||
        !/^\d/.test(marker[1] ?? "") ||
        /^0*1[.)]$/.test(marker[1] ?? ""));
    if (marker && opensList) {
      listColumn = indentOf(marker[0].slice(0, -1).replace(/\S/g, " "));
    } else if (indent < listColumn && !inParagraph) {
      listColumn = 0;
    }
    out.push(line);
    inParagraph = !HEADING_REGEX.test(rest);
  }
  flush();
  return out.join("\n");
}

/**
 * Answer markdown as the shared renderer parses it. Math is `$$…$$` only, so
 * "$5 and $10" stays text: `\[…\]` becomes block math and `\(…\)` inline
 * `$$…$$`. A trailing unclosed `$$` is escaped, so streaming LaTeX shows as
 * source until its closing `$$` arrives.
 *
 * Code (fenced, indented and inline) and complete `$$…$$` math are set aside
 * first, so the rewrites never change a code example or break a formula.
 */
export function prepareAnswerMarkdown(content: string): string {
  const kept: string[] = [];
  const keep = (text: string) => {
    kept.push(text);
    return `${PLACEHOLDER_OPEN}${kept.length - 1}${PLACEHOLDER_CLOSE}`;
  };
  let text = replaceFencedCodeBlocks(content, keep);
  text = replaceIndentedCode(text, keep);
  // A code span opens at the start of a backtick run, never inside one.
  text = text.replace(/(?<!`)(`+)(?!`)[\s\S]*?[^`]\1(?!`)/g, keep);
  text = text.replace(/\$\$[\s\S]+?\$\$/g, keep);

  text = preprocessLaTeX(escapeIncompleteBlockMath(text));

  // A kept span can hold another (e.g. inline code inside math).
  for (let pass = 0; pass < 3 && PLACEHOLDER_REGEX.test(text); pass++) {
    PLACEHOLDER_REGEX.lastIndex = 0;
    text = text.replace(
      PLACEHOLDER_REGEX,
      (match, index: string) => kept[Number(index)] ?? match
    );
  }
  return text;
}
