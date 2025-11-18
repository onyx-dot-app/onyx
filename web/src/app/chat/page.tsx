import AppPage from "@/refresh-components/layouts/AppPage";
import ChatPage from "@/app/chat/components/ChatPage";
import { SEARCH_PARAM_NAMES } from "./services/searchParams";
import { fetchSettingsSS } from "@/components/settings/lib";
import { fetchChatSessionSS } from "@/lib/chat/fetchChatSessionSS";

export interface PageProps {
  searchParams: Promise<{ [key: string]: string }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const chatSessionId = searchParams[SEARCH_PARAM_NAMES.CHAT_ID] ?? null;
  const settings = await fetchSettingsSS();
  const chatSession = chatSessionId
    ? await fetchChatSessionSS(chatSessionId)
    : null;

  const appPageProps = {
    chatSession,
    settings,
  };

  return (
    <AppPage {...appPageProps}>
      <ChatPage firstMessage={firstMessage} />
    </AppPage>
  );
}
