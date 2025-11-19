import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { ChatSession, toChatSession } from "@/app/chat/interfaces";
import { fetchSettingsSS } from "@/components/settings/lib";
import { fetchBackendChatSessionSS } from "@/lib/chat/fetchBackendChatSessionSS";

export interface HeaderData {
  settings: CombinedSettings | null;
  chatSession: ChatSession | null;
}

export async function fetchHeaderDataSS(
  chatSessionId?: string
): Promise<HeaderData> {
  const settings = await fetchSettingsSS();
  const backendChatSession = chatSessionId
    ? await fetchBackendChatSessionSS(chatSessionId)
    : null;
  const chatSession = backendChatSession
    ? toChatSession(backendChatSession)
    : null;

  return {
    settings,
    chatSession,
  };
}
