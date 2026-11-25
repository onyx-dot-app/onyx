"use client";

import { useEffect, useState } from "react";
import type { GrammarState } from "shiki/core";
import type { CodeHighlighter } from "@/lib/codeHighlight/highlighter";

/** Lines highlighted per task, so a long file never blocks input for long. */
const LINES_PER_TASK = 400;

interface Loaded {
  language: string;
  highlighter: CodeHighlighter;
}

/**
 * The Shiki highlighter for `language`, loaded with import() on first use.
 * Null until it loads, for an unknown language, or when `language` is
 * undefined: callers show plain text until then.
 */
export function useCodeHighlighter(
  language: string | undefined
): CodeHighlighter | null {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    if (!language || loaded?.language === language) return;
    let cancelled = false;
    import("@/lib/codeHighlight/highlighter")
      .then(({ loadCodeHighlighter }) => loadCodeHighlighter(language))
      .then((highlighter) => {
        if (!cancelled && highlighter) setLoaded({ language, highlighter });
      })
      .catch((error: unknown) => {
        console.error("Failed to load the code highlighter", error);
      });
    return () => {
      cancelled = true;
    };
  }, [language, loaded]);

  return loaded && loaded.language === language ? loaded.highlighter : null;
}

interface Highlighted {
  code: string;
  highlighter: CodeHighlighter;
  lines: string[];
}

/**
 * `code` as highlighted HTML lines, or null until they are ready. The work
 * runs after paint, a slice of lines per task, so plain text shows first and
 * the page stays responsive while a long file highlights.
 */
export function useHighlightedLines(
  code: string,
  language: string | undefined
): string[] | null {
  const highlighter = useCodeHighlighter(code ? language : undefined);
  const [highlighted, setHighlighted] = useState<Highlighted | null>(null);

  useEffect(() => {
    if (!highlighter) return;
    const source = code.split(/\r?\n/);
    const lines: string[] = [];
    let state: GrammarState | undefined;
    let next = 0;
    let timer: ReturnType<typeof setTimeout>;
    function highlightSlice(active: CodeHighlighter) {
      try {
        const slice = active.highlight(
          source.slice(next, next + LINES_PER_TASK).join("\n"),
          state
        );
        lines.push(...slice.lines);
        state = slice.state;
      } catch (error) {
        console.error("Failed to highlight code", { language, error });
        return;
      }
      next += LINES_PER_TASK;
      if (next < source.length) {
        timer = setTimeout(() => highlightSlice(active), 0);
      } else {
        setHighlighted({ code, highlighter: active, lines });
      }
    }
    timer = setTimeout(() => highlightSlice(highlighter), 0);
    return () => clearTimeout(timer);
  }, [code, highlighter, language]);

  return highlighted?.code === code && highlighted.highlighter === highlighter
    ? highlighted.lines
    : null;
}
