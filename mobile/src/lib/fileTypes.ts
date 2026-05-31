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
