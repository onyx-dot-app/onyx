import { fetchSS } from "@/lib/utilsSS";
import { redirect } from "next/navigation";
import { requireAuth } from "@/lib/auth/requireAuth";
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

  // Check authentication first
  const authResult = await requireAuth();
  if (authResult.redirect) {
    return redirect(authResult.redirect);
  }

  // Fetch shared chat data
  const chatSession = await getSharedChat(params.chatId);

  const persona: Persona = constructMiniFiedPersona(
    chatSession?.persona_icon_color ?? null,
    chatSession?.persona_icon_shape ?? null,
    chatSession?.persona_name ?? "",
    chatSession?.persona_id ?? 0
  );

  return <SharedChatDisplay chatSession={chatSession} persona={persona} />;
}
