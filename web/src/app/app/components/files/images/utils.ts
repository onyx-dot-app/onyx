const CHAT_FILE_URL_REGEX = /\/api\/chat\/file\/([^/?#]+)/;
const IMAGE_EXTENSIONS = /\.(png|jpe?g|gif|webp|svg|bmp|ico|tiff?)$/i;

export function buildImgUrl(fileId: string) {
  return `/api/chat/file/${fileId}`;
}

/**
 * If `href` points to a chat file and `linkText` ends with an image extension,
 * returns the file ID. Otherwise returns null.
 */
export function extractChatImageFileId(
  href: string | undefined,
  linkText: string
): string | null {
  if (!href) return null;
  const match = CHAT_FILE_URL_REGEX.exec(href);
  if (!match?.[1]) return null;
  if (!IMAGE_EXTENSIONS.test(linkText)) return null;
  return match[1];
}
