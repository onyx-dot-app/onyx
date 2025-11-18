import { BackendChatSession } from "@/app/chat/interfaces";
import { fetchSS } from "@/lib/utilsSS";

export async function fetchBackendChatSessionSS(
  chatSessionId: string,
  shared?: boolean
): Promise<BackendChatSession | null> {
  const url = `/chat/get-chat-session/${chatSessionId}?${
    shared ? "is_shared=True" : ""
  }`;
  const response = await fetchSS(url);
  return response.ok ? ((await response.json()) as BackendChatSession) : null;
}
