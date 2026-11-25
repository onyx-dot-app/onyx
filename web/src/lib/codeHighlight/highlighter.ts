// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).
// Heavy module: import it only with import() (see `useCodeHighlighter`), so
// Shiki stays out of the first-load bundle.

import {
  createHighlighterCore,
  stringifyTokenStyle,
  type GrammarState,
  type HighlighterCore,
} from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";
import { bundledLanguages, type BundledLanguage } from "shiki/langs";

const THEMES = {
  light: "github-light-default",
  dark: "github-dark-default",
} as const;

export interface HighlightedLines {
  /** HTML for each line: escaped source in colored spans. */
  lines: string[];
  /** The grammar state after the last line, to continue from. */
  state: GrammarState | undefined;
}

export interface CodeHighlighter {
  /**
   * Highlights `code` as one block, continuing from `state` when given.
   * Throws on a tokenizer error.
   */
  highlight(code: string, state?: GrammarState): HighlightedLines;
}

let highlighterPromise: Promise<HighlighterCore> | null = null;
const languagePromises = new Map<string, Promise<CodeHighlighter | null>>();

function getHighlighter(): Promise<HighlighterCore> {
  highlighterPromise ??= createHighlighterCore({
    themes: [
      import("shiki/themes/github-light-default.mjs"),
      import("shiki/themes/github-dark-default.mjs"),
    ],
    langs: [],
    engine: createJavaScriptRegexEngine({ forgiving: true }),
  }).catch((error: unknown) => {
    highlighterPromise = null;
    throw error;
  });
  return highlighterPromise;
}

function isBundledLanguage(language: string): language is BundledLanguage {
  return Object.hasOwn(bundledLanguages, language);
}

// Fence tags and file extensions that Shiki knows under another name.
const LANGUAGE_ALIASES = new Map<string, BundledLanguage>([
  ["gitignore", "ini"],
  ["dos", "bat"],
  ["golang", "go"],
  ["patch", "diff"],
  ["pwsh", "powershell"],
  ["h", "c"],
  ["cc", "cpp"],
  ["cxx", "cpp"],
  ["hh", "cpp"],
  ["hpp", "cpp"],
  ["hxx", "cpp"],
  ["h++", "cpp"],
  ["arduino", "cpp"],
  ["ino", "cpp"],
  ["apacheconf", "apache"],
  ["nginxconf", "nginx"],
  ["pgsql", "sql"],
  ["postgres", "sql"],
  ["postgresql", "sql"],
  ["ex", "elixir"],
  ["exs", "elixir"],
  ["feature", "gherkin"],
  ["pl", "perl"],
  ["pm", "perl"],
  ["objectivec", "objective-c"],
  ["obj-c", "objective-c"],
  ["mk", "makefile"],
  ["mak", "makefile"],
  ["svg", "xml"],
  ["xhtml", "xml"],
  ["rss", "xml"],
  ["atom", "xml"],
  ["xsd", "xml"],
  ["plist", "xml"],
  ["ipython", "python"],
  ["jsp", "java"],
  ["cr", "crystal"],
  ["hx", "haxe"],
  ["gradle", "groovy"],
  ["vbscript", "vb"],
  ["vbs", "vb"],
]);

function highlighterLanguageOf(language: string): string {
  const id = language.toLowerCase();
  return LANGUAGE_ALIASES.get(id) ?? id;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function createLanguageHighlighter(
  highlighter: HighlighterCore,
  language: BundledLanguage
): CodeHighlighter {
  return {
    highlight(code, state) {
      const result = highlighter.codeToTokens(code, {
        lang: language,
        themes: THEMES,
        defaultColor: false,
        grammarState: state,
      });
      return {
        lines: result.tokens.map((line) =>
          line
            .map((token) =>
              token.htmlStyle
                ? `<span style="${escapeHtml(stringifyTokenStyle(token.htmlStyle))}">${escapeHtml(token.content)}</span>`
                : escapeHtml(token.content)
            )
            .join("")
        ),
        state: result.grammarState,
      };
    },
  };
}

/**
 * A highlighter for `language` (an id or alias such as `ts`), loading the
 * shared Shiki core and the grammar on first use. Null for a language Shiki
 * does not bundle, such as `text`.
 */
export function loadCodeHighlighter(
  language: string
): Promise<CodeHighlighter | null> {
  const id = highlighterLanguageOf(language);
  if (!isBundledLanguage(id)) return Promise.resolve(null);
  let promise = languagePromises.get(id);
  if (!promise) {
    promise = getHighlighter().then(async (highlighter) => {
      await highlighter.loadLanguage(bundledLanguages[id]);
      return createLanguageHighlighter(highlighter, id);
    });
    promise.catch(() => languagePromises.delete(id));
    languagePromises.set(id, promise);
  }
  return promise;
}
