"use client";

import { useMemo } from "react";
import type { CodePanelLine } from "@opal/components";
import { useCodeHighlighter } from "@/lib/codeHighlight/hooks";

interface UseCodeLinesOptions {
  /**
   * The code still grows. Only its completed lines are highlighted as one
   * block, again each time a line completes; the line still arriving is
   * highlighted alone. So each update costs one line, not the whole block.
   */
  streaming?: boolean;
  /** Guess the language of untagged code once it stops growing. */
  detect?: boolean;
}

/**
 * Code as numbered `CodePanel` lines, highlighted once the highlighter loads
 * (plain text until then, or without a known language). The code is
 * highlighted as one block, so a block comment or a multi-line string keeps
 * its colors on every line.
 */
export function useCodeLines(
  code: string,
  language: string | undefined,
  { streaming = false, detect = false }: UseCodeLinesOptions = {}
): CodePanelLine[] {
  const highlighter = useCodeHighlighter(!!code && (!!language || detect));

  const detected = useMemo(
    () =>
      !language && detect && !streaming && highlighter
        ? highlighter.detectLanguage(code)
        : null,
    [language, detect, streaming, highlighter, code]
  );
  const resolvedLanguage = language ?? detected ?? undefined;

  // While streaming, `head` is the completed lines and `tail` the line still
  // arriving; otherwise `head` is all of the code.
  const split = streaming ? code.lastIndexOf("\n") : code.length;
  const head = split < 0 ? "" : code.slice(0, split);
  const tail = streaming ? code.slice(split + 1) : "";

  const headHtml = useMemo(
    () =>
      highlighter && resolvedLanguage && split >= 0
        ? highlighter.highlightLines(head, resolvedLanguage)
        : null,
    [highlighter, resolvedLanguage, head, split]
  );
  const tailHtml = useMemo(
    () =>
      highlighter && resolvedLanguage && tail
        ? (highlighter.highlightLines(tail, resolvedLanguage)?.[0] ?? null)
        : null,
    [highlighter, resolvedLanguage, tail]
  );

  return useMemo(() => {
    const lines = code.split("\n");
    const headCount = streaming ? lines.length - 1 : lines.length;
    return lines.map((line, index) => {
      const html = index < headCount ? headHtml?.[index] : tailHtml;
      return {
        number: index + 1,
        content:
          html != null ? (
            <span dangerouslySetInnerHTML={{ __html: html || " " }} />
          ) : (
            line
          ),
      };
    });
  }, [code, streaming, headHtml, tailHtml]);
}
