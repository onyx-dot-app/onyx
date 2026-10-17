/**
 * Trigger a browser file download.
 *
 * Supports two modes:
 *  1. **From content** — pass `content` (string or Blob) and optional `mimeType`.
 *     A Blob is created, downloaded, and the object URL is revoked.
 *  2. **From URL** — pass `url` (string). The browser navigates to the
 *     URL with the `download` attribute set.
 */
export function downloadFile(
  filename: string,
  opts: { content: string | Blob; mimeType?: string } | { url: string }
): void {
  const a: HTMLAnchorElement = document.createElement("a");
  let objectUrl: string | undefined;

  if ("content" in opts) {
    const blob: Blob =
      typeof opts.content === "string"
        ? new Blob([opts.content], { type: opts.mimeType ?? "text/plain" })
        : opts.content;
    objectUrl = URL.createObjectURL(blob);
    a.href = objectUrl;
  } else {
    a.href = opts.url;
  }
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  if (objectUrl) {
    const url: string = objectUrl;
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
