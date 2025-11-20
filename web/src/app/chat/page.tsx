import * as Layouts from "@/refresh-components/layouts/layouts";
import ChatPage from "@/app/chat/components/ChatPage";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";
import { SEARCH_PARAM_NAMES } from "./services/searchParams";

export interface PageProps {
  searchParams: Promise<{ [key: string]: string }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const chatSessionId = searchParams[SEARCH_PARAM_NAMES.CHAT_ID];
  const headerData = await fetchHeaderDataSS(chatSessionId);

  return (
    <Layouts.AppPage {...headerData}>
      <ChatPage firstMessage={firstMessage} />
    </Layouts.AppPage>
  );
}
