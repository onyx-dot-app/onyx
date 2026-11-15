import mime from "mime";

const EXTENSION_PATTERN = /\.[^./\\\s]+$/;

function decodeExtendedFileName(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

/** Read the file name from a Content-Disposition header, preferring the RFC 5987 `filename*`. */
export function parseContentDispositionFileName(
  header: string | null
): string | null {
  if (!header) return null;

  const extendedMatch = header.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  const extendedFileName = extendedMatch?.[1]
    ? decodeExtendedFileName(extendedMatch[1].trim())
    : null;
  if (extendedFileName) return extendedFileName;

  const quotedMatch = header.match(/filename\s*=\s*"([^"]*)"/i);
  if (quotedMatch?.[1]) return quotedMatch[1];

  const bareMatch = header.match(/filename\s*=\s*([^;]+)/i);
  return bareMatch?.[1]?.trim() || null;
}

/** Append the extension for `mimeType` when `fileName` has none. */
export function withMimeTypeExtension(
  fileName: string,
  mimeType: string
): string {
  if (EXTENSION_PATTERN.test(fileName)) return fileName;
  const extension = mime.getExtension(mimeType);
  if (!extension || extension === "bin") return fileName;
  return `${fileName}.${extension}`;
}
