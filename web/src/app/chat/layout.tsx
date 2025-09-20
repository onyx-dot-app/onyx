import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "@/components/context/ChatContext";
import AppSidebar from "@/sections/AppSidebar";
import { fetchAppSidebarMetadata } from "@/lib/appSidebarSS";
import { getCurrentUserSS } from "@/lib/userSS";
import { AppSidebarProvider } from "@/components-2/context/AppSidebarContext";

export default async function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  noStore();

  // Ensure searchParams is an object, even if it's empty
  const safeSearchParams = {};

  const [user, data] = await Promise.all([
    getCurrentUserSS(),
    fetchChatData(safeSearchParams),
  ]);

  const { folded } = await fetchAppSidebarMetadata(user);

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
    availableTools,
    sidebarInitiallyVisible,
    defaultAssistantId,
    shouldShowWelcomeModal,
    ccPairs,
    inputPrompts,
    proSearchToggled,
  } = data;

  return (
    <>
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
          availableTools,
          shouldShowWelcomeModal,
          defaultAssistantId,
        }}
      >
        <AppSidebarProvider folded={folded}>
          <div className="flex flex-row">
            <AppSidebar />
            {children}
          </div>
        </AppSidebarProvider>
      </ChatProvider>
    </>
  );
}
