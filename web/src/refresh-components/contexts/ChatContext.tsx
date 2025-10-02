"use client";

import React, { createContext, useContext, useState } from "react";
import {
  CCPairBasicInfo,
  DocumentSetSummary,
  Tag,
  ValidSources,
} from "@/lib/types";
import { ChatSession, InputPrompt } from "@/app/chat/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { fetchProjects } from "@/app/chat/projects/projectsService";

// We use Omit to exclude some fields that are defined within the component
export interface ChatProviderProps
  extends Omit<
    ChatContextProps,
    "currentChat" | "refreshChatSessions" | "refreshInputPrompts"
  > {
  children: React.ReactNode;
}

export function ChatProvider({
  children,
  inputPrompts: initialInputPrompts,
  chatSessions: initialChatSessions,
  ...otherProps
}: ChatProviderProps) {
  const router = useRouter();
  const [inputPrompts, setInputPrompts] = useState(initialInputPrompts || []);
  const [chatSessions, setChatSessions] = useState(initialChatSessions || []);

  const searchParams = useSearchParams();
  const currentChatId = searchParams?.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const currentChat =
    chatSessions.find((chatSession) => chatSession.id === currentChatId) ||
    null;

  async function refreshChatSessions() {
    try {
      const response = await fetch("/api/chat/get-user-chat-sessions");
      if (!response.ok) throw new Error("Failed to fetch chat sessions");
      const { sessions } = await response.json();
      const projects = await fetchProjects();
      const projectSessions = projects.flatMap(
        (project) => project.chat_sessions
      );
      setChatSessions(sessions);

      const allChatSession = [...sessions, ...projectSessions];

      if (
        currentChatId &&
        !allChatSession.some(
          (session: ChatSession) => session.id === currentChatId
        )
      ) {
        router.replace("/chat");
      }
    } catch (error) {
      console.error("Error refreshing chat sessions:", error);
    }
  }

  async function refreshInputPrompts() {
    const response = await fetch("/api/input_prompt");
    if (!response.ok) throw new Error("Failed to fetch input prompts");
    const inputPrompts = await response.json();
    setInputPrompts(inputPrompts);
  }

  return (
    <ChatContext.Provider
      value={{
        ...otherProps,
        currentChat,
        refreshChatSessions,
        refreshInputPrompts,

        inputPrompts,
        chatSessions,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

interface ChatContextProps {
  // Chat related:
  chatSessions: ChatSession[];
  currentChat: ChatSession | null;

  // LLM related:
  llmProviders: LLMProviderDescriptor[];

  sidebarInitiallyVisible: boolean;
  availableSources: ValidSources[];
  ccPairs: CCPairBasicInfo[];
  tags: Tag[];
  documentSets: DocumentSetSummary[];
  availableDocumentSets: DocumentSetSummary[];
  availableTags: Tag[];
  availableTools: ToolSnapshot[];
  shouldShowWelcomeModal?: boolean;
  shouldDisplaySourcesIncompleteModal?: boolean;
  defaultAssistantId?: number;
  refreshChatSessions: () => Promise<void>;
  refreshInputPrompts: () => Promise<void>;
  inputPrompts: InputPrompt[];
  proSearchToggled: boolean;
}

const ChatContext = createContext<ChatContextProps | undefined>(undefined);

export function useChatContext(): ChatContextProps {
  const context = useContext(ChatContext);
  if (!context)
    throw new Error("useChatContext must be used within a ChatProvider");
  return context;
}
