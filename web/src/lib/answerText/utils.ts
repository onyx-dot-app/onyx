import {
  escapeIncompleteBlockMath,
  preprocessLaTeX,
  replaceFencedCodeBlocks,
} from "@/app/app/message/codeUtils";

// Private-use characters: no math or markdown rewrite matches them.
const PLACEHOLDER_OPEN = "\uE000";
const PLACEHOLDER_CLOSE = "\uE001";
const PLACEHOLDER_REGEX = /\uE000(\d+)\uE001/g;
const LIST_ITEM_REGEX = /^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]/;
const INDENTED_REGEX = /^(?: {4}|\t)/;

/**
 * Indented code blocks: runs of lines indented 4+ spaces (or a tab) after a
 * blank line, outside a list item, whose indented lines continue it.
 */
function replaceIndentedCode(
  content: string,
  replace: (block: string) => string
): string {
  const lines = content.split("\n");
  const out: string[] = [];
  let block: string[] | null = null;
  // The last non-blank line before the current blank run, if any.
  let lastText: string | null = null;
  let afterBlank = true;
  for (const line of lines) {
    const blank = line.trim() === "";
    if (block !== null) {
      if (INDENTED_REGEX.test(line) || (blank && block.length > 0)) {
        block.push(line);
        continue;
      }
      // Trailing blank lines belong after the block.
      const trailing: string[] = [];
      while (
        block.length > 0 &&
        (block[block.length - 1] ?? "").trim() === ""
      ) {
        trailing.unshift(block.pop() ?? "");
      }
      out.push(replace(block.join("\n")), ...trailing);
      block = null;
    }
    if (
      !blank &&
      afterBlank &&
      INDENTED_REGEX.test(line) &&
      (lastText === null ||
        (!INDENTED_REGEX.test(lastText) && !LIST_ITEM_REGEX.test(lastText)))
    ) {
      block = [line];
      continue;
    }
    out.push(line);
    if (!blank) lastText = line;
    afterBlank = blank;
  }
  if (block !== null) out.push(replace(block.join("\n")));
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
  text = text.replace(/(`+)(?!`)[\s\S]*?[^`]\1(?!`)/g, keep);
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
