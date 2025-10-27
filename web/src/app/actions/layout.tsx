import {
  SidebarLayout,
  getSidebarUser,
} from "@/components/admin/SidebarLayout";
import AppSidebar from "@/sections/sidebar/AppSidebar";
import { ChatProvider } from "@/refresh-components/contexts/ChatContext";
import { ChatModalProvider } from "@/refresh-components/contexts/ChatModalContext";
import { ProjectsProvider } from "@/app/chat/projects/ProjectsContext";
import { UserRole } from "@/lib/types";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { redirect } from "next/navigation";

export default async function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  const sidebarUser = await getSidebarUser();
  if (sidebarUser?.role !== UserRole.BASIC) {
    return <SidebarLayout user={sidebarUser}>{children}</SidebarLayout>;
  }
  const safeSearchParams = {};
  const data = await fetchChatData(
    safeSearchParams as { [key: string]: string }
  );
  if ("redirect" in data) {
    return redirect(data.redirect);
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
        <ChatModalProvider>
          <ProjectsProvider initialProjects={projects}>
            <div className="flex flex-row w-full h-full">
              <AppSidebar />
              <div className="flex-1 p-10 overflow-auto">{children}</div>
            </div>
          </ProjectsProvider>
        </ChatModalProvider>
      </ChatProvider>
    </>
  );
}
