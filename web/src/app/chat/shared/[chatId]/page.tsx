import { redirect } from "next/navigation";
import { requireAuth } from "@/lib/auth/requireAuth";
import { SharedChatDisplay } from "./SharedChatDisplay";
import { Persona } from "@/app/admin/assistants/interfaces";
import { constructMiniFiedPersona } from "@/lib/assistantIconUtils";
import AppPage from "@/refresh-components/layouts/AppPage";
import { fetchSettingsSS } from "@/components/settings/lib";
import { fetchBackendChatSessionSS } from "@/lib/chat/fetchChatSessionSS";
import { toChatSession } from "@/app/chat/interfaces";

export interface PageProps {
  params: Promise<{ chatId: string }>;
}

export default async function Page(props: PageProps) {
  const params = await props.params;

  const authResult = await requireAuth();
  if (authResult.redirect) {
    return redirect(authResult.redirect);
  }

  // Catch cases where backend is completely unreachable
  // Allows render instead of throwing an exception and crashing
  const backendChatSession = await fetchBackendChatSessionSS(
    params.chatId,
    true
  ).catch(() => null);
  const settings = await fetchSettingsSS();
  const persona: Persona = constructMiniFiedPersona(
    backendChatSession?.persona_icon_color ?? null,
    backendChatSession?.persona_icon_shape ?? null,
    backendChatSession?.persona_name ?? "",
    backendChatSession?.persona_id ?? 0
  );
  const chatSession = backendChatSession
    ? toChatSession(backendChatSession)
    : null;

  const appPageProps = {
    settings,
    chatSession,
  };

  return (
    <AppPage {...appPageProps}>
      <SharedChatDisplay chatSession={backendChatSession} persona={persona} />
    </AppPage>
  );
}
