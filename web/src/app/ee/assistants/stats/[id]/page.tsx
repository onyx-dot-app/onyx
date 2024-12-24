import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";

import { fetchChatData } from "@/lib/chat/fetchChatData";
import { unstable_noStore as noStore } from "next/cache";
import { redirect } from "next/navigation";

import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { cookies } from "next/headers";
import { ChatProvider } from "@/components/context/ChatContext";
import WrappedAssistantsStats from "./WrappedAssistantsStats";

export default async function GalleryPage(props: {
  params: Promise<{ id: string }>;
}) {
  const params = await props.params;
  noStore();
  const requestCookies = await cookies();

  const data = await fetchChatData({});

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
      <WrappedAssistantsStats
        initiallyToggled={toggleSidebar}
        assistantId={parseInt(params.id)}
      />
    </ChatProvider>
  );
}
