import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { ChatProvider } from "@/components/context/ChatContext";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { cookies } from "next/headers";
import WrappedNRF from "./WrappedNRF";
import { NEXT_PUBLIC_ENABLE_CHROME_EXTENSION } from "@/lib/constants";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  noStore();
  const requestCookies = await cookies();
  const data = await fetchChatData(searchParams);

  if ("redirect" in data) {
    redirect(data.redirect);
  }

  if (!NEXT_PUBLIC_ENABLE_CHROME_EXTENSION) {
    redirect("/chat");
  }

  const {
    user,
    chatSessions,
    availableSources,
    documentSets,
    tags,
    llmProviders,
    folders,
    toggleSidebar,
    openedFolders,
    defaultAssistantId,
    shouldShowWelcomeModal,
    ccPairs,
  } = data;

  return (
    <>
      <InstantSSRAutoRefresh />
      {shouldShowWelcomeModal && (
        <WelcomeModal user={user} requestCookies={requestCookies} />
      )}
      <ChatProvider
        value={{
          chatSessions,
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
        <WrappedNRF initiallyToggled={toggleSidebar} />
      </ChatProvider>
    </>
  );
}
