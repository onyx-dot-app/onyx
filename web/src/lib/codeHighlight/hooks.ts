"use client";

import { useEffect, useState } from "react";
import type { CodeHighlighter } from "@/lib/codeHighlight/highlighter";

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
