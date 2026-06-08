// Mirrors web utils.ts (`IMAGE_EXTENSIONS` / `isImageFile`).

export const IMAGE_EXTENSIONS = [
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "svg",
  "bmp",
] as const;

export function isImageFile(fileName: string | null | undefined): boolean {
  if (!fileName) return false;
  const lower = String(fileName).toLowerCase();
  return IMAGE_EXTENSIONS.some((ext) => lower.endsWith(`.${ext}`));
}

// `txt` maps to "PLAINTEXT" to match web's `FileLineItem`; pass
// `{ plaintextForTxt: false }` for call sites that plainly upper-case (web
// `FileCard.typeLabel` has no special case).
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
