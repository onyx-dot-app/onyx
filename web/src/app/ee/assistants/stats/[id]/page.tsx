import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { unstable_noStore as noStore } from "next/cache";
import { redirect } from "next/navigation";
import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { cookies } from "next/headers";
import { ChatProvider } from "@/refresh-components/contexts/ChatContext";
import { AssistantStats } from "./AssistantStats";
import { BackButton } from "@/components/BackButton";

export default async function GalleryPage(props: {
  params: Promise<{ id: string }>;
}) {
  const params = await props.params;
  noStore();
  const requestCookies = await cookies();

  const data = await fetchChatData({});

  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const {
    user,
    chatSessions,
    sidebarInitiallyVisible,
    shouldShowWelcomeModal,
    availableSources,
    ccPairs,
    documentSets,
    availableTools,
    tags,
    llmProviders,
    defaultAssistantId,
    inputPrompts,
    proSearchToggled,
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
      {shouldShowWelcomeModal && (
        <WelcomeModal user={user} requestCookies={requestCookies} />
      )}
      <div className="absolute top-4 left-4">
        <BackButton />
      </div>

      <div className="w-full py-8">
        <div className="px-32">
          <InstantSSRAutoRefresh />
          <div className="max-w-4xl  mx-auto !border-none !bg-transparent !ring-none">
            <AssistantStats assistantId={parseInt(params.id)} />
          </div>
        </div>
      </div>
    </ChatProvider>
  );
}
