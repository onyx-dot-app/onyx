import ChatPage from "@/app/chat/components/ChatPage";
import { SEARCH_PARAM_NAMES } from "./services/searchParams";

export interface PageProps {
  searchParams: Promise<{ [key: string]: string }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;

  // Other pages in `web/src/app/chat` are wrapped with `<AppPageLayout>`.
  // `chat/page.tsx` is not because it also needs to handle rendering of the document-sidebar (`web/src/sections/document-sidebar/DocumentsSidebar.tsx`).
  return <ChatPage firstMessage={firstMessage} />;
}
