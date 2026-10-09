const CHAT_FILE_PREFIX = "/api/chat/file";

/**
 * Fetch a chat file by its ID, returning the raw Response.
 *
 * The caller is responsible for consuming the body (e.g. `.blob()`,
 * `.text()`) since different consumers need different formats.
 *
 * When `parsed` is true, spreadsheet files (xlsx) are returned as a JSON
 * payload of per-sheet CSV text instead of raw binary bytes; the param is a
 * no-op for all other file types.
 */
export async function fetchChatFile(
  fileId: string,
  parsed: boolean = false
): Promise<Response> {
  const response = await fetch(
    `${CHAT_FILE_PREFIX}/${encodeURIComponent(fileId)}${
      parsed ? "?parsed=true" : ""
    }`,
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
