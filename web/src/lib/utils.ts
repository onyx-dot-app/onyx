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
 * Custom URL transformer function for ReactMarkdown
 * Allows specific protocols to be used in markdown links
 * We use this with the urlTransform prop in ReactMarkdown
 */
export function transformLinkUri(href: string) {
  if (!href) return href;

  const url = href.trim();
  try {
    const parsedUrl = new URL(url);
    if (
      ALLOWED_URL_PROTOCOLS.some((protocol) =>
        parsedUrl.protocol.startsWith(protocol)
      )
    ) {
      return url;
    }
  } catch {
    // If it's not a valid URL with protocol, return the original href
    return href;
  }
  return href;
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
