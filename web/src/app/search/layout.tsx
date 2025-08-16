import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "@/components/context/ChatContext";
import MainPageFrame from "@/components-2/MainPageFrame";
import { SidebarProvider } from "@/components/context/SidebarProvider";
import { DocumentsProvider } from "../chat/my-documents/DocumentsContext";

type LayoutProps = {
  children: React.ReactNode;
};

export default async function Layout({ children }: LayoutProps) {
  noStore();

  // Ensure searchParams is an object, even if it's empty
  const safeSearchParams = {};

  const data = await fetchChatData(
    safeSearchParams as { [key: string]: string }
  );

  if ("redirect" in data) {
    console.log("redirect", data.redirect);
    redirect(data.redirect);
  }

  const {
    chatSessions,
    availableSources,
    documentSets,
    tags,
    llmProviders,
    folders,
    openedFolders,
    sidebarInitiallyVisible,
    defaultAssistantId,
    shouldShowWelcomeModal,
    ccPairs,
    inputPrompts,
    proSearchToggled,
  } = data;

  return (
    <ChatProvider
      value={{
        proSearchToggled,
        inputPrompts,
        chatSessions,
        sidebarInitiallyVisible,
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
      <SidebarProvider>
        <DocumentsProvider>
          <MainPageFrame>{children}</MainPageFrame>
        </DocumentsProvider>
      </SidebarProvider>
    </ChatProvider>
  );
}
