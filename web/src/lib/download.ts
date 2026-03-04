/**
 * Trigger a browser file download.
 *
 * Supports two modes:
 *  1. **From content** — pass `content` (string) and optional `mimeType`.
 *     A Blob is created, downloaded, and the object URL is revoked.
 *  2. **From URL** — pass `url` (string). The browser navigates to the
 *     URL with the `download` attribute set.
 */
export function downloadFile(
  filename: string,
  opts: { content: string; mimeType?: string } | { url: string }
): void {
  const a = document.createElement("a");

  if ("content" in opts) {
    const blob = new Blob([opts.content], {
      type: opts.mimeType ?? "text/plain",
    });
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } else {
    a.href = opts.url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}
