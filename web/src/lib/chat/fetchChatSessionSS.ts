import {
  BackendChatSession,
  ChatSession,
  toChatSession,
} from "@/app/chat/interfaces";
import { fetchSS } from "@/lib/utilsSS";

export async function fetchBackendChatSessionSS(
  chatSessionId: string,
  shared?: boolean
): Promise<BackendChatSession | null> {
  const url = `/chat/get-chat-session/${chatSessionId}?${
    shared ? "is_shared=True" : ""
  }`;
  const response = await fetchSS(url);
  if (!response.ok) return null;
  return (await response.json()) as BackendChatSession;
}

export async function fetchChatSessionSS(
  chatSessionId: string,
  shared?: boolean
): Promise<ChatSession | null> {
  const backendChatSession = await fetchBackendChatSessionSS(
    chatSessionId,
    shared
  );
  if (!backendChatSession) return null;
  return toChatSession(backendChatSession);
}
