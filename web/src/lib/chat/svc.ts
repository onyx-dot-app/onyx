const CHAT_FILE_PREFIX = "/api/chat/file";

/**
 * Fetch a chat file by its ID, returning the raw Response.
 *
 * The caller is responsible for consuming the body (e.g. `.blob()`,
 * `.text()`) since different consumers need different formats.
 */
export async function fetchChatFile(fileId: string): Promise<Response> {
  const response = await fetch(
    `${CHAT_FILE_PREFIX}/${encodeURIComponent(fileId)}`,
    {
      method: "GET",
      cache: "force-cache",
    }
  );

  if (!response.ok) {
    throw new Error("Failed to load document.");
  }

  return response;
}
