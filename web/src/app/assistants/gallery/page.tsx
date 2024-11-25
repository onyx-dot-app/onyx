import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { unstable_noStore as noStore } from "next/cache";
import { redirect } from "next/navigation";
import WrappedAssistantsGallery from "./WrappedAssistantsGallery";
import { cookies } from "next/headers";

export default async function GalleryPage(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  noStore();

  const searchParams = await props.searchParams;
  const requestCookies = await cookies();
  const data = await fetchChatData(searchParams);

  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const {
    user,
    chatSessions,
    folders,
    openedFolders,
    toggleSidebar,
    shouldShowWelcomeModal,
  } = data;

  return (
    <>
      {shouldShowWelcomeModal && (
        <WelcomeModal user={user} requestCookies={requestCookies} />
      )}

      <InstantSSRAutoRefresh />

      <WrappedAssistantsGallery
        initiallyToggled={toggleSidebar}
        chatSessions={chatSessions}
        folders={folders}
        openedFolders={openedFolders}
      />
    </>
  );
}
