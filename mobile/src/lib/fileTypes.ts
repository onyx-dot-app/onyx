// Filename-based image detection — ported from web `web/src/lib/utils.ts`
// (`IMAGE_EXTENSIONS` / `isImageFile`). Used to decide whether a recent /
// document-picked file renders as an image thumbnail.

export const IMAGE_EXTENSIONS = [
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "svg",
  "bmp",
] as const;

/** True when the filename ends in a known image extension (case-insensitive). */
export function isImageFile(fileName: string | null | undefined): boolean {
  if (!fileName) return false;
  const lower = String(fileName).toLowerCase();
  return IMAGE_EXTENSIONS.some((ext) => lower.endsWith(`.${ext}`));
}

/**
 * Short, upper-case extension label for a filename (e.g. "report.pdf" → "PDF").
 * Returns "" when there is no usable extension (no dot, leading dot, trailing
 * dot).
 *
 * By default the `txt` extension maps to "PLAINTEXT" to match web's
 * `FileLineItem`. Pass `{ plaintextForTxt: false }` for call sites that plainly
 * upper-case the extension (web `FileCard.typeLabel` has no special case).
 */
export function fileExtensionLabel(
  name: string,
  options?: { plaintextForTxt?: boolean },
): string {
  const idx = name.lastIndexOf(".");
  if (idx <= 0 || idx === name.length - 1) return "";
  const ext = name.slice(idx + 1).toLowerCase();
  const plaintextForTxt = options?.plaintextForTxt ?? true;
  return plaintextForTxt && ext === "txt" ? "PLAINTEXT" : ext.toUpperCase();
}
