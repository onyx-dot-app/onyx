import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "@/refresh-components/context/ChatContext";
import { ProjectsProvider } from "./projects/ProjectsContext";
import AppSidebar from "@/sections/sidebar/AppSidebar";

export default async function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
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
    user,
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
    projects,
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
        <ProjectsProvider initialProjects={projects}>
          <div className="flex flex-row w-full h-full">
            <AppSidebar />
            {children}
          </div>
        </ProjectsProvider>
      </ChatProvider>
    </>
  );
}
