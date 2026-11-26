"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CodePanelLine } from "@opal/components";
import { useCodeHighlighter } from "@/lib/codeHighlight/hooks";

/** The least time between two highlight passes over streaming code. */
const STREAMING_HIGHLIGHT_MS = 250;

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

  // Finished code is highlighted at once. While code streams, the
  // completed lines are highlighted again at most every
  // STREAMING_HIGHLIGHT_MS, so a long block does not rescan its whole head
  // on every new line; lines since the last pass show as plain text.
  const doneHtml = useMemo(
    () =>
      !streaming && highlighter && resolvedLanguage && split >= 0
        ? highlighter.highlightLines(head, resolvedLanguage)
        : null,
    [streaming, highlighter, resolvedLanguage, head, split]
  );
  const [streamedHtml, setStreamedHtml] = useState<string[] | null>(null);
  // When the last pass ran. A new line moves the pass to this plus
  // STREAMING_HIGHLIGHT_MS, so lines that keep arriving cannot delay it.
  const lastPass = useRef(0);
  useEffect(() => {
    if (!streaming || !highlighter || !resolvedLanguage || split < 0) return;
    const pass = setTimeout(
      () => {
        lastPass.current = Date.now();
        setStreamedHtml(highlighter.highlightLines(head, resolvedLanguage));
      },
      Math.max(0, lastPass.current + STREAMING_HIGHLIGHT_MS - Date.now())
    );
    return () => clearTimeout(pass);
  }, [streaming, highlighter, resolvedLanguage, head, split]);
  const headHtml = streaming ? streamedHtml : doneHtml;
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
