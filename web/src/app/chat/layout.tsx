import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "@/components-2/context/ChatContext";
import AppSidebar from "@/sections/sidebar/AppSidebar";
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
        proSearchToggled={proSearchToggled}
        inputPrompts={inputPrompts}
        chatSessions={chatSessions}
        sidebarInitiallyVisible={sidebarInitiallyVisible}
        availableSources={availableSources}
        ccPairs={ccPairs}
        documentSets={documentSets}
        tags={tags}
        availableDocumentSets={documentSets}
        availableTags={tags}
        llmProviders={llmProviders}
        availableTools={availableTools}
        shouldShowWelcomeModal={shouldShowWelcomeModal}
        defaultAssistantId={defaultAssistantId}
      >
        <AppSidebarProvider folded={folded}>
          <div className="flex flex-row w-full h-full">
            <AppSidebar />
            <div className="w-full h-full">
              {children}
            </div>
          </div>
        </AppSidebarProvider>
      </ChatProvider>
    </>
  );
}
