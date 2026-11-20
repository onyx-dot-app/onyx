// Heavy module: pulls in highlight.js, every grammar lowlight ships plus ABAP,
// and the hljs theme CSS. It is imported ONLY via dynamic import() (see
// `useCodeHighlighter`), so it stays out of the first-load bundle and is
// fetched the first time code needs highlighting.

import hljs from "highlight.js/lib/core";
import { all } from "lowlight";
import abap from "highlightjs-sap-abap";

// hljs theme styles. Loads with this chunk, not on first paint.
import "@/app/app/message/custom-code-styles.css";

for (const [name, language] of Object.entries({ ...all, abap })) {
  hljs.registerLanguage(name, language);
}

/** A guess must score at least this to color an untagged block. */
const MIN_DETECTED_RELEVANCE = 7;

const HTML_TOKEN = /<span[^>]*>|<\/span>|\n|[^<\n]+/g;

// Splits hljs HTML into one string per source line. A span that is open at a
// line break closes at the end of that line and opens again on the next, so
// each line is valid markup on its own.
function splitHtmlLines(html: string): string[] {
  const lines: string[] = [];
  const open: string[] = [];
  let line = "";
  for (const [token] of html.matchAll(HTML_TOKEN)) {
    if (token === "\n") {
      lines.push(line + "</span>".repeat(open.length));
      line = open.join("");
    } else if (token === "</span>") {
      open.pop();
      line += token;
    } else if (token.startsWith("<span")) {
      open.push(token);
      line += token;
    } else {
      line += token;
    }
  }
  lines.push(line);
  return lines;
}

/**
 * Highlights `code` as one block, so constructs that span lines (block
 * comments, multi-line strings) keep their colors, and returns hljs HTML
 * (escaped source and hljs spans) for each line. Null for an unknown language
 * or any internal error.
 */
export function highlightLines(
  code: string,
  language: string
): string[] | null {
  try {
    if (!hljs.getLanguage(language)) return null;
    return splitHtmlLines(
      hljs.highlight(code, { language, ignoreIllegals: true }).value
    );
  } catch {
    return null;
  }
}

/** The language of untagged code, or null when no guess is confident. */
export function detectLanguage(code: string): string | null {
  try {
    const result = hljs.highlightAuto(code);
    return result.language && result.relevance >= MIN_DETECTED_RELEVANCE
      ? result.language
      : null;
  } catch {
    return null;
  }
}
