import { DocumentsProvider } from "./my-documents/DocumentsContext";
import { SEARCH_PARAMS } from "@/lib/extension/constants";
import { ChatPage } from "./ChatPage";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const defaultSidebarOff =
    searchParams[SEARCH_PARAMS.DEFAULT_SIDEBAR_OFF] === "true";

  return (
    <DocumentsProvider>
      <ChatPage firstMessage={firstMessage} />
    </DocumentsProvider>
  );
}
