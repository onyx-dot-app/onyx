import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { ChatPage } from "./ChatPage";
import { NoCompleteSourcesModal } from "@/components/initialSetup/search/NoCompleteSourceModal";
import { ChatProvider } from "@/components/context/ChatContext";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { fetchEEASettings } from "@/lib/eea/fetchEEASettings";
import { UserDisclaimerModal } from "@/components/search/UserDisclaimerModal";

export default async function Page({
  searchParams,
}: {
  searchParams: { [key: string]: string };
}) {
  noStore();

  const data = await fetchChatData(searchParams);


  if ("redirect" in data) {
    redirect(data.redirect);
  }
 
  const config = await fetchEEASettings();
  
  const {
    eea_config,
    disclaimerTitle,
    disclaimerText
  } = config;

  const {
    user,
    chatSessions,
    ccPairs,
    availableSources,
    documentSets,
    personas,
    tags,
    llmProviders,
    folders,
    openedFolders,
    defaultPersonaId,
    finalDocumentSidebarInitialWidth,
    shouldShowWelcomeModal,
    shouldDisplaySourcesIncompleteModal,
  } = data;

  return (
    <>
      <UserDisclaimerModal disclaimerText={disclaimerText} disclaimerTitle={disclaimerTitle}/>

      <InstantSSRAutoRefresh />

      {shouldShowWelcomeModal && <WelcomeModal user={user} />}
      {!shouldShowWelcomeModal && !shouldDisplaySourcesIncompleteModal && (
        <ApiKeyModal user={user} />
      )}
      {shouldDisplaySourcesIncompleteModal && (
        <NoCompleteSourcesModal ccPairs={ccPairs} />
      )}

      <ChatProvider
        value={{
          user,
          chatSessions,
          availableSources,
          availableDocumentSets: documentSets,
          availablePersonas: personas,
          availableTags: tags,
          llmProviders,
          folders,
          openedFolders,
          }}
      >
        <ChatPage
          defaultSelectedPersonaId={defaultPersonaId}
          documentSidebarInitialWidth={finalDocumentSidebarInitialWidth}
          eea_config={eea_config}
        />
      </ChatProvider>
    </>
  );
}
