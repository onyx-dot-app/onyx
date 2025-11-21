import { BackendChatSession } from "@/app/chat/interfaces";
import { fetchSS } from "@/lib/utilsSS";

export async function fetchBackendChatSessionSS(
  chatId: string
): Promise<BackendChatSession | null> {
  const response = await fetchSS(`/chat/get-chat-session/${chatId}`);
  if (!response.ok) return null;
  return (await response.json()) as BackendChatSession;
}
