import { BackendChatSession } from "@/app/chat/interfaces";
import { fetchSS } from "@/lib/utilsSS";

export async function fetchChatSessionSS(
  chatId: string
): Promise<BackendChatSession | null> {
  const response = await fetchSS(
    `/chat/get-chat-session/${chatId}?is_shared=True`
  );
  if (!response.ok) return null;
  return await response.json();
}
