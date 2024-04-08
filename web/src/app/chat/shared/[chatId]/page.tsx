import { User } from "@/lib/types";
import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { fetchSS } from "@/lib/utilsSS";
import { redirect } from "next/navigation";
import { BackendChatSession } from "../../interfaces";
import { Header } from "@/components/Header";
import { SharedChatDisplay } from "./SharedChatDisplay";
import { getSettingsSS } from "@/lib/settings";
import { Settings } from "@/app/admin/settings/interfaces";

async function getSharedChat(chatId: string) {
  const response = await fetchSS(
    `/chat/get-chat-session/${chatId}?is_shared=True`
  );
  if (response.ok) {
    return await response.json();
  }
  return null;
}

export default async function Page({ params }: { params: { chatId: string } }) {
  const tasks = [
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
    getSharedChat(params.chatId),
    getSettingsSS(),
  ];

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let results: (User | AuthTypeMetadata | null)[] = [null, null, null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }
  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;
  const chatSession = results[2] as BackendChatSession | null;
  const settings = results[3] as Settings | null;

  const authDisabled = authTypeMetadata?.authType === "disabled";
  if (!authDisabled && !user) {
    return redirect("/auth/login");
  }

  if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
    return redirect("/auth/waiting-on-verification");
  }

  return (
    <div>
      <div className="absolute top-0 z-40 w-full">
        <Header user={user} settings={settings} />
      </div>

      <div className="flex relative bg-background text-default overflow-hidden pt-16 h-screen">
        <SharedChatDisplay chatSession={chatSession} />
      </div>
    </div>
  );
}
