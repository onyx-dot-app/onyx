import { fetchChatData } from "@/lib/chat/fetchChatData";
import WrappedDocuments from "./WrappedDocuments";
import { redirect } from "next/navigation";
import { ChatProvider } from "@/components/context/ChatContext";

export default async function GalleryPage(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const data = await fetchChatData(searchParams);

  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const {
    chatSessions,
    toggleSidebar,
    shouldShowWelcomeModal,
    availableSources,
    ccPairs,
    documentSets,
    tags,
    llmProviders,
    defaultAssistantId,
  } = data;

  return (
    <ChatProvider
      value={{
        chatSessions,
        availableSources,
        ccPairs,
        documentSets,
        tags,
        availableDocumentSets: documentSets,
        availableTags: tags,
        llmProviders,
        shouldShowWelcomeModal,
        defaultAssistantId,
      }}
    >
      <WrappedDocuments initiallyToggled={toggleSidebar} />
    </ChatProvider>
  );
}
