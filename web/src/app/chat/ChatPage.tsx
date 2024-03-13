"use client";

import { useSearchParams } from "next/navigation";
import { ChatSession } from "./interfaces";
import { ChatSidebar } from "./sessionSidebar/ChatSidebar";
import { Chat } from "./Chat";
import { DocumentSet, Tag, User, ValidSources } from "@/lib/types";
import { Persona } from "../admin/personas/interfaces";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";

export function ChatLayout({
  user,
  chatSessions,
  availableSources,
  availableDocumentSets,
  availablePersonas,
  availableTags,
  defaultSelectedPersonaId,
  documentSidebarInitialWidth,
}: {
  user: User | null;
  chatSessions: ChatSession[];
  availableSources: ValidSources[];
  availableDocumentSets: DocumentSet[];
  availablePersonas: Persona[];
  availableTags: Tag[];
  defaultSelectedPersonaId?: number; // what persona to default to
  documentSidebarInitialWidth?: number;
}) {
  const searchParams = useSearchParams();
  const chatIdRaw = searchParams.get("chatId");
  const chatId = chatIdRaw ? parseInt(chatIdRaw) : null;

  const selectedChatSession = chatSessions.find(
    (chatSession) => chatSession.id === chatId
  );

  return (
    <>
      <div className="absolute top-0 z-40 w-full">
        <Header user={user} />
      </div>
      <HealthCheckBanner />
      <InstantSSRAutoRefresh />

      <div className="flex relative bg-background text-default overflow-x-hidden">
        <ChatSidebar
          existingChats={chatSessions}
          currentChatSession={selectedChatSession}
          user={user}
        />

        <Chat
          existingChatSessionId={chatId}
          existingChatSessionPersonaId={selectedChatSession?.persona_id}
          availableSources={availableSources}
          availableDocumentSets={availableDocumentSets}
          availablePersonas={availablePersonas}
          availableTags={availableTags}
          defaultSelectedPersonaId={defaultSelectedPersonaId}
          documentSidebarInitialWidth={documentSidebarInitialWidth}
        />
      </div>
      <Footer />
    </>
  );
}
