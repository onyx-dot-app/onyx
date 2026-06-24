import { useEffect, useState } from "react";
import type { LanguageFn } from "highlight.js";
import { loadHighlightLanguages } from "@/lib/highlightLanguages";

/**
 * Dynamically loads syntax-highlighting grammars and returns them once ready,
 * or null until then. Pass `enabled=false` to defer the load (e.g. while a
 * message is still streaming) so the grammar corpus stays off the critical path.
 */
export function useHighlightLanguages(
  enabled: boolean = true
): Record<string, LanguageFn> | null {
  const [languages, setLanguages] = useState<Record<string, LanguageFn> | null>(
    null
  );

  useEffect(() => {
    if (!enabled || languages) return;
    let cancelled = false;
    void loadHighlightLanguages().then((langs) => {
      if (!cancelled) setLanguages(langs);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, languages]);

  return languages;
}
