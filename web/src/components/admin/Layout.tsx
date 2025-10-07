import { User, UserRole } from "@/lib/types";
import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { ClientLayout } from "./ClientLayout";
import {
  NEXT_PUBLIC_CLOUD_ENABLED,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { AnnouncementBanner } from "../header/AnnouncementBanner";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "../../refresh-components/contexts/ChatContext";

export async function Layout({ children }: { children: React.ReactNode }) {
  const tasks = [getAuthTypeMetadataSS(), getCurrentUserSS()];

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let results: (User | AuthTypeMetadata | null)[] = [null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }

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
