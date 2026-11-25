/**
 * Map a file path's extension to a Shiki language id. Pure and
 * dependency-free (no Shiki), so it's safe to import statically — the
 * heavy highlighter itself lives in `highlighter.ts` and is loaded lazily.
 */
export function getLanguageFromPath(
  filePath: string | undefined
): string | undefined {
  if (!filePath) return undefined;
  const ext = filePath.split(".").pop()?.toLowerCase();
  if (!ext) return undefined;

  const langMap: Record<string, string> = {
    js: "javascript",
    jsx: "jsx",
    ts: "typescript",
    tsx: "tsx",
    py: "python",
    json: "json",
    css: "css",
    html: "html",
    xml: "xml",
    sh: "bash",
    bash: "bash",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    sql: "sql",
  };

  return langMap[ext];
}
