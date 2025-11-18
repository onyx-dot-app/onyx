import ChatPage from "./components/ChatPage";
import ShareChatLayout from "@/refresh-components/layouts/ShareChatLayout";
import { ChatSession, toChatSession } from "./interfaces";
import { fetchSS } from "@/lib/utilsSS";
import { SEARCH_PARAM_NAMES } from "./services/searchParams";

async function fetchChatSession(chatId: string): Promise<ChatSession | null> {
  const response = await fetchSS(`/chat/get-chat-session/${chatId}`);
  if (!response.ok) {
    return null;
  }
  const backendSession = await response.json();
  return toChatSession(backendSession);
}

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const chatSessionId = searchParams[SEARCH_PARAM_NAMES.CHAT_ID] ?? null;
  const chatSession = chatSessionId
    ? await fetchChatSession(chatSessionId)
    : null;

  return (
    <ShareChatLayout chatSession={chatSession}>
      <ChatPage firstMessage={firstMessage} />
    </ShareChatLayout>
  );
}
