import { redirect } from "next/navigation";

import { ChatProvider } from "@/refresh-components/contexts/ChatContext";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { AuthLayout } from "@/components/admin/AuthLayout";
import {
  SidebarLayout,
  getSidebarUser,
} from "@/components/admin/SidebarLayout";

export async function Layout({ children }: { children: React.ReactNode }) {
  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;
  const authDisabled = authTypeMetadata?.authType === "disabled";
  const requiresVerification = authTypeMetadata?.requiresVerification;

  if (!authDisabled) {
    if (!user) {
      return redirect("/auth/login");
    }
    if (user.role === UserRole.BASIC) {
      return redirect("/chat");
    }
    if (!user.is_verified && requiresVerification) {
      return redirect("/auth/waiting-on-verification");
    }
  }

  // Fetch chat data (will verify auth again - defense in depth)
  const data = await fetchChatData({});
  const user = await getSidebarUser();
  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const {
    chatSessions,
    availableSources,
    documentSets,
    tags,
    llmProviders,
    sidebarInitiallyVisible,
    defaultAssistantId,
    shouldShowWelcomeModal,
    ccPairs,
    inputPrompts,
    proSearchToggled,
    availableTools,
    projects,
  } = data;

  return await AuthLayout({
    children: (
      <ChatProvider
        inputPrompts={inputPrompts}
        chatSessions={chatSessions}
        proSearchToggled={proSearchToggled}
        sidebarInitiallyVisible={sidebarInitiallyVisible}
        availableSources={availableSources}
        ccPairs={ccPairs}
        documentSets={documentSets}
        availableTools={availableTools}
        tags={tags}
        availableDocumentSets={documentSets}
        availableTags={tags}
        llmProviders={llmProviders}
        shouldShowWelcomeModal={shouldShowWelcomeModal}
        defaultAssistantId={defaultAssistantId}
      >
        <SidebarLayout user={user}>{children}</SidebarLayout>
      </ChatProvider>
    ),
  });
}
