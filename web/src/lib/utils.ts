import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { ALLOWED_URL_PROTOCOLS } from "./constants";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const truncateString = (str: string, maxLength: number) => {
  return str.length > maxLength ? str.slice(0, maxLength - 1) + "..." : str;
};

/**
 * Ensures an href has a protocol, adding https:// only to bare domains.
 * Preserves existing protocols, relative paths, anchors, mailto:, and tel: links.
 */
export function ensureHrefProtocol(
  href: string | undefined
): string | undefined {
  if (!href) return href;
  const needsProtocol =
    !href.includes("://") &&
    !href.startsWith("/") &&
    !href.startsWith("#") &&
    !href.startsWith("mailto:") &&
    !href.startsWith("tel:");
  return needsProtocol ? `https://${href}` : href;
}

/**
 * Custom URL transformer function for ReactMarkdown.
 * Only allows a small, safe set of protocols and strips everything else.
 * Returning null removes the href attribute entirely.
 */
export function transformLinkUri(href: string): string | null {
  if (!href) return null;

  const trimmedHref = href.trim();
  if (!trimmedHref) return null;

  try {
    const parsedUrl = new URL(trimmedHref);
    const protocol = parsedUrl.protocol.toLowerCase();

    if (ALLOWED_URL_PROTOCOLS.some((allowed) => allowed === protocol)) {
      return trimmedHref;
    }

    return null;
  } catch {
    // Allow relative URLs, but drop anything that looks like a protocol-prefixed link
    if (/^[a-zA-Z][a-zA-Z\d+.-]*:\S*/.test(trimmedHref)) {
      return null;
    }

    return trimmedHref;
  }
}

export function isSubset(parent: string[], child: string[]): boolean {
  const parentSet = new Set(parent);
  return Array.from(new Set(child)).every((item) => parentSet.has(item));
}

export function trinaryLogic<T>(
  a: boolean | undefined,
  b: boolean,
  ifTrue: T,
  ifFalse: T
): T {
  const condition = a !== undefined ? a : b;
  return condition ? ifTrue : ifFalse;
}

// A convenience function to prevent propagation of click events to items higher up in the DOM tree.
//
// # Note:
// This is a desired behaviour in MANY locations, since we have buttons nested within buttons.
// When the nested button is pressed, the click event that triggered it should (in most scenarios) NOT trigger its parent button!
export function noProp(
  f?: (event: React.MouseEvent) => void
): React.MouseEventHandler {
  return (event) => {
    event.stopPropagation();
    f?.(event);
  };
}

/**
 * Extracts the file extension from a filename and returns it in uppercase.
 * Returns an empty string if no valid extension is found.
 */
export function getFileExtension(fileName: string): string {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
}

/**
 * Centralized list of image file extensions (lowercase, no leading dots)
 */
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

/**
 * Checks whether a provided extension string corresponds to an image extension.
 * Accepts values with any casing and without a leading dot.
 */
export function isImageExtension(
  extension: string | null | undefined
): boolean {
  if (!extension) {
    return false;
  }
  const normalized = extension.toLowerCase();
  return (IMAGE_EXTENSIONS as readonly string[]).includes(normalized);
}

/**
 * Formats bytes to human-readable file size.
 */
export function formatBytes(
  bytes: number | undefined,
  decimals: number = 2
): string {
  if (bytes == null) return "Unknown";
  if (bytes === 0) return "0 Bytes";

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];

  let unitIndex = Math.floor(Math.log(bytes) / Math.log(k));
  if (unitIndex < 0) unitIndex = 0;
  if (unitIndex >= sizes.length) unitIndex = sizes.length - 1;
  return (
    parseFloat((bytes / Math.pow(k, unitIndex)).toFixed(dm)) +
    " " +
    sizes[unitIndex]
  );
}

/**
 * Checks if a filename represents an image file based on its extension.
 */
export function isImageFile(fileName: string | null | undefined): boolean {
  if (!fileName) return false;
  const lowerFileName = String(fileName).toLowerCase();
  return IMAGE_EXTENSIONS.some((ext) => lowerFileName.endsWith(`.${ext}`));
}

/**
 * Checks if a collection of files contains any non-image files.
 * Useful for determining whether image previews should be compact.
 */
export function hasNonImageFiles(
  files: Array<{ name?: string | null }>
): boolean {
  return files.some((file) => !isImageFile(file.name));
}
