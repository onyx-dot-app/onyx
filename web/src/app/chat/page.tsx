import ChatSessionLayout from "@/refresh-components/layouts/ChatSessionLayout";
import ChatPage from "./components/ChatPage";
import { SEARCH_PARAM_NAMES } from "./services/searchParams";
import { fetchSS } from "@/lib/utilsSS";
import { BackendChatSession, ChatSession, toChatSession } from "./interfaces";

export interface PageProps {
  searchParams: Promise<{ [key: string]: string }>;
}

async function fetchChatSession(
  chatSessionId: string
): Promise<ChatSession | null> {
  try {
    const response = await fetchSS(`/chat/get-chat-session/${chatSessionId}`);
    if (!response.ok) {
      return null;
    }
    const backendSession: BackendChatSession = await response.json();
    return toChatSession(backendSession);
  } catch (error) {
    console.error("Failed to fetch chat session:", error);
    return null;
  }
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const chatSessionId = searchParams[SEARCH_PARAM_NAMES.CHAT_ID] ?? null;
  const chatSession = chatSessionId
    ? await fetchChatSession(chatSessionId)
    : null;

  return (
    <ChatSessionLayout chatSession={chatSession}>
      <ChatPage firstMessage={firstMessage} />
    </ChatSessionLayout>
  );
}
