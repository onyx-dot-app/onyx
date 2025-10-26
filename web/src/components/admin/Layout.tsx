import { redirect } from "next/navigation";
import { requireAdminAuth } from "@/lib/auth/requireAuth";
import { ClientLayout } from "./ClientLayout";
import {
  NEXT_PUBLIC_CLOUD_ENABLED,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { AnnouncementBanner } from "../header/AnnouncementBanner";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "../../refresh-components/contexts/ChatContext";

export async function Layout({ children }: { children: React.ReactNode }) {
  // Check authentication and admin role
  const authResult = await requireAdminAuth();

  // If auth check returned a redirect, redirect immediately
  if (authResult.redirect) {
    return redirect(authResult.redirect);
  }

  const { user } = authResult;

  // Fetch chat data (will verify auth again - defense in depth)
  const data = await fetchChatData({});
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

  return (
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
      <ClientLayout
        enableEnterprise={SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED}
        enableCloud={NEXT_PUBLIC_CLOUD_ENABLED}
        user={user}
      >
        <AnnouncementBanner />
        {children}
      </ClientLayout>
    </ChatProvider>
  );
}
