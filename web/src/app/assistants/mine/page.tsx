import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";

import { fetchChatData } from "@/lib/chat/fetchChatData";
import { unstable_noStore as noStore } from "next/cache";
import { redirect } from "next/navigation";
import WrappedAssistantsMine from "./WrappedAssistantsMine";
import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { cookies } from "next/headers";
import { ChatProvider } from "@/components/context/ChatContext";

export default async function GalleryPage(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  noStore();
  const requestCookies = await cookies();
  const searchParams = await props.searchParams;

  const data = await fetchChatData(searchParams);

  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const {
    user,
    chatSessions,
    folders,
    openedFolders,
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
        folders,
        openedFolders,
        shouldShowWelcomeModal,
        defaultAssistantId,
      }}
    >
      {shouldShowWelcomeModal && (
        <WelcomeModal user={user} requestCookies={requestCookies} />
      )}

      <InstantSSRAutoRefresh />
      <WrappedAssistantsMine initiallyToggled={toggleSidebar} />
    </ChatProvider>
  );
}
