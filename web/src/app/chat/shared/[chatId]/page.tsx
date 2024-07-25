import { User } from "@/lib/types";
import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { fetchSS } from "@/lib/utilsSS";
import { redirect } from "next/navigation";
import { BackendChatSession } from "../../interfaces";
import { Header } from "@/components/header/Header";
import { SharedChatDisplay } from "./SharedChatDisplay";
import { Persona } from "@/app/admin/assistants/interfaces";
import { fetchAssistantsSS } from "@/lib/assistants/fetchAssistantsSS";

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
    fetchAssistantsSS(),
  ];

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let results: (User | AuthTypeMetadata | [Persona[], string | null] | null)[] =
    [null, null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }
  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;
  const chatSession = results[2] as BackendChatSession | null;
  const [availableAssistants, _] = results[3] as [Persona[], string | null];

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
        <Header user={user} />
      </div>

      <div className="flex relative bg-background text-default overflow-hidden pt-16 h-screen">
        <SharedChatDisplay
          chatSession={chatSession}
          availableAssistants={availableAssistants}
        />
      </div>
    </div>
  );
}
