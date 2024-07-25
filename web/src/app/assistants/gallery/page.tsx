import { HistorySidebar } from "@/app/chat/sessionSidebar/HistorySidebar";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { UserDropdown } from "@/components/UserDropdown";
import { ChatProvider } from "@/components/context/ChatContext";
import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { unstable_noStore as noStore } from "next/cache";
import { redirect } from "next/navigation";
import { AssistantsGallery } from "./AssistantsGallery";
import FixedLogo from "@/app/chat/shared_chat_search/FixedLogo";
import GalleryWrapper from "../SidebarWrapper";
import WrappedAssistantsGallery from "./WrappedAssistantsGallery";

export default async function GalleryPage({
  searchParams,
}: {
  searchParams: { [key: string]: string };
}) {
  noStore();

  const data = await fetchChatData(searchParams);

  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const {
    user,
    chatSessions,
    availableSources,
    documentSets,
    assistants,
    tags,
    llmProviders,
    folders,
    openedFolders,
    shouldShowWelcomeModal,
    toggleSidebar,
  } = data;

  return (
    <>
      <InstantSSRAutoRefresh />

      {shouldShowWelcomeModal && <WelcomeModal user={user} />}

      <ChatProvider
        value={{
          user,
          chatSessions,
          availableSources,
          availableDocumentSets: documentSets,
          availableAssistants: assistants,
          availableTags: tags,
          llmProviders,
          folders,
          openedFolders,
        }}
      >
        <WrappedAssistantsGallery
          initiallyToggled={toggleSidebar}
          chatSessions={chatSessions}
          folders={folders}
          openedFolders={openedFolders}
          user={user}
          assistants={assistants}
        />
      </ChatProvider>
    </>
  );
}
