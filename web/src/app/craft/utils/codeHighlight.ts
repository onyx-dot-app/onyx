// Heavy module: pulls in highlight.js + a set of languages + the hljs theme
// CSS. It is imported ONLY via dynamic import() (see useCodeHighlighter) so
// highlight.js is code-split out of the craft first-load bundle and fetched
// lazily the first time a tool body actually needs syntax highlighting.

import hljs from "highlight.js/lib/core";

// hljs theme styles (Atom One Dark). Loads with this chunk, not on first paint.
import "@/app/app/message/custom-code-styles.css";

import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import json from "highlight.js/lib/languages/json";
import css from "highlight.js/lib/languages/css";
import xml from "highlight.js/lib/languages/xml"; // includes HTML
import bash from "highlight.js/lib/languages/bash";
import yaml from "highlight.js/lib/languages/yaml";
import markdown from "highlight.js/lib/languages/markdown";
import sql from "highlight.js/lib/languages/sql";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("jsx", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("tsx", typescript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("json", json);
hljs.registerLanguage("css", css);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("shell", bash);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("md", markdown);
hljs.registerLanguage("sql", sql);

/**
 * Highlight a single line of code, returning hljs HTML (escaped source + hljs
 * spans). Falls back to null on unknown language or any internal error.
 */
export function highlightLineHtml(
  line: string,
  language: string | undefined
): string | null {
  if (!language) return null;
  try {
    if (!hljs.getLanguage(language)) return null;
    return hljs.highlight(line, { language, ignoreIllegals: true }).value;
  } catch {
    return null;
  }
}
