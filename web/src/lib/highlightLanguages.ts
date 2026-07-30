import type { LanguageFn } from "highlight.js";

let cache: Record<string, LanguageFn> | null = null;

/**
 * Dynamically loads the full highlight.js grammar set (lowlight's `all`) plus
 * ABAP, which is not part of highlight.js core. Loaded via `import()` so the
 * ~170 KB grammar corpus stays out of the initial client bundle; cached so it
 * resolves at most once per session.
 */
export async function loadHighlightLanguages(): Promise<
  Record<string, LanguageFn>
> {
  if (!cache) {
    const [{ all }, { default: abap }] = await Promise.all([
      import("lowlight"),
      import("highlightjs-sap-abap"),
    ]);
    cache = { ...all, abap };
  }
  return cache;
}
