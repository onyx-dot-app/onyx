import { chatFileUrl } from "@/lib/api";

// expo-image source for an authed backend image (`GET /chat/file/{id}`). The
// route requires the bearer header, so we return `undefined` until the headers
// resolve — that defers loading until auth is ready and avoids firing a
// guaranteed-401 request on first paint (web rides cookies, so it has no
// equivalent gate).
export interface AuthedImageSource {
  uri: string;
  headers: Record<string, string>;
}

export function authedChatImageSource(
  apiBaseUrl: string,
  fileId: string,
  headers: Record<string, string> | undefined,
): AuthedImageSource | undefined {
  if (!headers) return undefined;
  return { uri: chatFileUrl(apiBaseUrl, fileId), headers };
}
