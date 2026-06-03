"use client";

import { useEffect, useState } from "react";

type HighlightFn = (
  line: string,
  language: string | undefined
) => string | null;

/**
 * Lazily loads the highlight.js-backed highlighter (`codeHighlight.ts`) so hljs
 * is split out of the first-load bundle. Returns `null` until the chunk
 * resolves; callers render plain text in the meantime and re-render with
 * highlighting once it's ready. Pass `enabled=false` to skip loading entirely
 * (e.g. when there's nothing to highlight).
 */
export function useCodeHighlighter(enabled: boolean): HighlightFn | null {
  const [highlight, setHighlight] = useState<HighlightFn | null>(null);

  useEffect(() => {
    if (!enabled || highlight) return;
    let cancelled = false;
    void import("@/app/craft/utils/codeHighlight").then((m) => {
      if (!cancelled) setHighlight(() => m.highlightLineHtml);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, highlight]);

  return highlight;
}
