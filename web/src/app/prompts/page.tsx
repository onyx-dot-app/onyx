import { fetchChatData } from "@/lib/chat/fetchChatData";
import { unstable_noStore as noStore } from "next/cache";
import { redirect } from "next/navigation";
import WrappedPrompts from "../assistants/mine/WrappedInputPrompts";

export default async function GalleryPage({
  searchParams,
}: {
  searchParams: { [key: string]: string };
}) {
  noStore();

  const data = await fetchChatData(searchParams);

  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const { chatSessions, folders, openedFolders, toggleSidebar } = data;

  return (
    <WrappedPrompts
      initiallyToggled={toggleSidebar}
      chatSessions={chatSessions}
      folders={folders}
      openedFolders={openedFolders}
    />
  );
}
