import { chatFileUrl } from "@/lib/api";

// Returns undefined until the bearer header resolves, deferring the image load
// until auth is ready — otherwise first paint fires a guaranteed 401 (web rides
// cookies, so it has no equivalent gate).
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
