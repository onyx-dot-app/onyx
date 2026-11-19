"use client";

import { useMemo } from "react";
import type { CodePanelLine } from "@opal/components";
import { useCodeHighlighter } from "@/app/craft/hooks/useCodeHighlighter";

/**
 * Code as numbered `CodePanel` lines, each highlighted on its own once the
 * highlighter loads (plain text until then, or without a language).
 */
export function useCodeLines(
  code: string,
  language: string | undefined
): CodePanelLine[] {
  const highlight = useCodeHighlighter(!!code && !!language);
  return useMemo(
    () =>
      code.split("\n").map((line, index) => {
        const html = highlight ? highlight(line, language) : null;
        return {
          number: index + 1,
          content:
            html !== null ? (
              <span dangerouslySetInnerHTML={{ __html: html || " " }} />
            ) : (
              line
            ),
        };
      }),
    [code, language, highlight]
  );
}
