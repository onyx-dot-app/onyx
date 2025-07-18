import { User } from "@/lib/types";
import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { fetchSS } from "@/lib/utilsSS";
import { redirect } from "next/navigation";
import { BackendChatSession } from "../../interfaces";
import { SharedChatDisplay } from "./SharedChatDisplay";
import { Persona } from "@/app/admin/assistants/interfaces";
import { constructMiniFiedPersona } from "@/lib/assistantIconUtils";

async function getSharedChat(chatId: string) {
  const response = await fetchSS(
    `/chat/get-chat-session/${chatId}?is_shared=True`
  );
  if (response.ok) {
    return await response.json();
  }
  return null;
}

export default async function Page(props: {
  params: Promise<{ chatId: string }>;
}) {
  const params = await props.params;
  const tasks = [
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
    getSharedChat(params.chatId),
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

  const authDisabled = authTypeMetadata?.authType === "disabled";
  if (!authDisabled && !user) {
    return redirect("/auth/login");
  }

  if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
    return redirect("/auth/waiting-on-verification");
  }

  const persona: Persona = constructMiniFiedPersona(
    chatSession?.persona_icon_color ?? null,
    chatSession?.persona_icon_shape ?? null,
    chatSession?.persona_name ?? "",
    chatSession?.persona_id ?? 0
  );

  return <SharedChatDisplay chatSession={chatSession} persona={persona} />;
}
