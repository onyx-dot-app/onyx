"use client";

import { useEffect, useState } from "react";

export type CodeHighlighter = typeof import("@/lib/codeHighlight/highlighter");

/**
 * Lazily loads the highlight.js-backed highlighter (`highlighter.ts`) so hljs
 * and its grammars are split out of the first-load bundle. Returns `null`
 * until the chunk resolves; callers render plain text in the meantime and
 * re-render with highlighting once it's ready. Pass `enabled=false` to skip
 * loading entirely (e.g. when there's nothing to highlight).
 */
export function useCodeHighlighter(enabled: boolean): CodeHighlighter | null {
  const [highlighter, setHighlighter] = useState<CodeHighlighter | null>(null);

  useEffect(() => {
    if (!enabled || highlighter) return;
    let cancelled = false;
    import("@/lib/codeHighlight/highlighter")
      .then((module) => {
        if (!cancelled) setHighlighter(module);
      })
      .catch((error) => {
        // The chunk failed to load; code stays plain rather than rejecting
        // unhandled.
        console.error("Failed to load the code highlighter", error);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, highlighter]);

  return highlighter;
}
