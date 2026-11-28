import { errorHandlingFetchWith } from "@/lib/fetcher";

function browserRoute(sessionId: string, action: string): string {
  return `/api/chat/sessions/${encodeURIComponent(sessionId)}/browser/${action}`;
}

/** The route that serves a file the chat's browser downloaded. */
export function browserDownloadUrl(
  sessionId: string,
  fileName: string
): string {
  return browserRoute(sessionId, `downloads/${encodeURIComponent(fileName)}`);
}

/**
 * Uploads files for the page's file chooser into the chat's session dir.
 * Returns their paths relative to it, for the `fileChooser` answer.
 */
export async function uploadBrowserFiles(
  sessionId: string,
  files: readonly File[]
): Promise<string[]> {
  const body = new FormData();
  for (const file of files) body.append("files", file);
  const response = await errorHandlingFetchWith<{ paths: unknown }>(
    browserRoute(sessionId, "upload"),
    { method: "POST", body }
  );
  const { paths } = response;
  if (
    !Array.isArray(paths) ||
    !paths.every((path): path is string => typeof path === "string")
  )
    throw new Error("The upload returned no file paths");
  return paths;
}

/** Clears the user's browser data: sign-ins, cookies and history. */
export async function clearBrowserData(sessionId: string): Promise<void> {
  // The route may answer with no body, so only the status counts
  const response = await fetch(browserRoute(sessionId, "clear"), {
    method: "POST",
  });
  if (!response.ok)
    throw new Error(`Clearing browser data failed: ${response.status}`);
}

/** Ends the chat's use of the user's Chrome. */
export async function stopChromeShare(sessionId: string): Promise<void> {
  const response = await fetch(browserRoute(sessionId, "chrome"), {
    method: "DELETE",
  });
  if (!response.ok)
    throw new Error(`Stopping the Chrome share failed: ${response.status}`);
}
