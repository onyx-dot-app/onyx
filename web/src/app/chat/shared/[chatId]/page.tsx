import { fetchSS } from "@/lib/utilsSS";
import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAuth } from "@/lib/auth/requireAuth";
import SharedChatDisplay from "@/app/chat/shared/[chatId]/SharedChatDisplay";
import * as AppLayouts from "@/layouts/app-layouts";
import { Persona } from "@/app/admin/assistants/interfaces";

// This is used for rendering a persona in the shared chat display
export function constructMiniFiedPersona(name: string, id: number): Persona {
  return {
    id,
    name,
    is_visible: true,
    is_public: true,
    display_priority: 0,
    description: "",
    document_sets: [],
    tools: [],
    owner: null,
    starter_messages: null,
    builtin_persona: false,
    is_default_persona: false,
    users: [],
    groups: [],
    user_file_ids: [],
    system_prompt: null,
    task_prompt: null,
    datetime_aware: true,
    replace_base_system_prompt: false,
  };
}

async function getSharedChat(chatId: string) {
  const response = await fetchSS(
    `/chat/get-chat-session/${chatId}?is_shared=True`
  );
  if (response.ok) {
    return await response.json();
  }
  return null;
}

export interface PageProps {
  params: Promise<{ chatId: string }>;
}

export default async function Page(props: PageProps) {
  const params = await props.params;

  const authResult = await requireAuth();
  if (authResult.redirect) {
    return redirect(authResult.redirect as Route);
  }

  // Catch cases where backend is completely unreachable
  // Allows render instead of throwing an exception and crashing
  const chatSession = await getSharedChat(params.chatId).catch(() => null);

  const persona: Persona = constructMiniFiedPersona(
    chatSession?.persona_name ?? "",
    chatSession?.persona_id ?? 0
  );

  return (
    <AppLayouts.Root>
      <SharedChatDisplay chatSession={chatSession} persona={persona} />
    </AppLayouts.Root>
  );
}
