"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { useMemo } from "react";
import type { CodePanelLine } from "@opal/components";
import type { GrammarState } from "shiki/core";
import type { CodeHighlighter } from "@/lib/codeHighlight/highlighter";
import {
  MAX_HIGHLIGHTED_CHARACTERS,
  useCodeHighlighter,
} from "@/lib/codeHighlight/hooks";

interface UseCodeLinesOptions {
  /** The code still grows: its last line shows plain until it completes. */
  streaming?: boolean;
}

/**
 * Highlights completed lines once each. Code that only grows continues from
 * the grammar state after the last line, so each update costs the new lines,
 * and a block comment or multi-line string keeps its colors on every line.
 */
function createIncrementalHighlighter(
  highlighter: CodeHighlighter,
  language: string | undefined
) {
  let failed = false;
  let source = "";
  let lines: string[] = [];
  let state: GrammarState | undefined;

  return (completed: string): string[] | null => {
    if (failed) return null;
    const next = `${completed}\n`;
    if (!next.startsWith(source)) {
      source = "";
      lines = [];
      state = undefined;
    }
    if (next.length > source.length) {
      try {
        const result = highlighter.highlight(
          next.slice(source.length, -1),
          state
        );
        lines = [...lines, ...result.lines];
        state = result.state;
        source = next;
      } catch (error) {
        failed = true;
        console.error("Failed to highlight code", { language, error });
        return null;
      }
    }
    return lines;
  };
}

/**
 * Code as numbered `CodePanel` lines. Plain text paints first; Shiki tokens
 * replace it once the grammar loads. Unknown languages stay plain, and so
 * does finished code above `MAX_HIGHLIGHTED_CHARACTERS`.
 */
export function useCodeLines(
  code: string,
  language: string | undefined,
  { streaming = false }: UseCodeLinesOptions = {}
): CodePanelLine[] {
  const highlightable =
    code.length > 0 && (streaming || code.length <= MAX_HIGHLIGHTED_CHARACTERS);
  const highlighter = useCodeHighlighter(highlightable ? language : undefined);
  const incremental = useMemo(
    () =>
      highlighter ? createIncrementalHighlighter(highlighter, language) : null,
    [highlighter, language]
  );

  const split = streaming ? code.lastIndexOf("\n") : code.length;
  const completed = split < 0 ? null : code.slice(0, split);
  const html = useMemo(
    () => (incremental && completed !== null ? incremental(completed) : null),
    [incremental, completed]
  );

  return useMemo(
    () =>
      code.split("\n").map((line, index) => {
        const lineHtml = html?.[index];
        return {
          number: index + 1,
          content:
            lineHtml != null ? (
              <span dangerouslySetInnerHTML={{ __html: lineHtml || " " }} />
            ) : (
              line
            ),
        };
      }),
    [code, html]
  );
}
