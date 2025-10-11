/**
 * Extracts the file extension from a filename and returns it in uppercase.
 * Returns an empty string if no valid extension is found.
 */
export function getFileExtension(fileName: string): string {
  const name = String(fileName || "");
  const lastDotIndex = name.lastIndexOf(".");
  if (lastDotIndex <= 0 || lastDotIndex === name.length - 1) {
    return "";
  }
  return name.slice(lastDotIndex + 1).toUpperCase();
}

// Centralized list of image file extensions (lowercase, no leading dots)
export const IMAGE_EXTENSIONS = [
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "svg",
  "bmp",
] as const;

export type ImageExtension = (typeof IMAGE_EXTENSIONS)[number];

// Checks whether a provided extension string corresponds to an image extension.
// Accepts values with any casing and without a leading dot.
export function isImageExtension(
  extension: string | null | undefined
): boolean {
  if (!extension) {
    return false;
  }
  const normalized = extension.toLowerCase();
  return (IMAGE_EXTENSIONS as readonly string[]).includes(normalized);
}
