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
import { Project } from "@/app/chat/projects/projectsService";

interface ChatContextProps {
  chatSessions: ChatSession[];
  sidebarInitiallyVisible: boolean;
  availableSources: ValidSources[];
  ccPairs: CCPairBasicInfo[];
  tags: Tag[];
  documentSets: DocumentSetSummary[];
  availableDocumentSets: DocumentSetSummary[];
  availableTags: Tag[];
  availableTools: ToolSnapshot[];
  llmProviders: LLMProviderDescriptor[];
  shouldShowWelcomeModal?: boolean;
  shouldDisplaySourcesIncompleteModal?: boolean;
  defaultAssistantId?: number;
  refreshChatSessions: (options?: {
    skipRedirectOnMissing?: boolean;
  }) => Promise<void>;
  refreshInputPrompts: () => Promise<void>;
  inputPrompts: InputPrompt[];
  proSearchToggled: boolean;
  projects: Project[];
}

const ChatContext = createContext<ChatContextProps | undefined>(undefined);

// We use Omit to exclude 'refreshChatSessions' from the value prop type
// because we're defining it within the component
export const ChatProvider: React.FC<{
  value: Omit<
    ChatContextProps,
    "refreshChatSessions" | "refreshAvailableAssistants" | "refreshInputPrompts"
  >;
  children: React.ReactNode;
}> = ({ value, children }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [inputPrompts, setInputPrompts] = useState(value?.inputPrompts || []);
  const [chatSessions, setChatSessions] = useState(value?.chatSessions || []);

  const refreshChatSessions = async (options?: {
    skipRedirectOnMissing?: boolean;
  }) => {
    try {
      const response = await fetch("/api/chat/get-user-chat-sessions");
      if (!response.ok) throw new Error("Failed to fetch chat sessions");
      const { sessions } = await response.json();
      setChatSessions(sessions);

      const currentSessionId = searchParams?.get("chatId");
      if (
        currentSessionId &&
        !sessions.some(
          (session: ChatSession) => session.id === currentSessionId
        )
      ) {
        if (!options?.skipRedirectOnMissing) {
          router.replace("/chat");
        }
      }
    } catch (error) {
      console.error("Error refreshing chat sessions:", error);
    }
  };

  const refreshInputPrompts = async () => {
    const response = await fetch("/api/input_prompt");
    if (!response.ok) throw new Error("Failed to fetch input prompts");
    const inputPrompts = await response.json();
    setInputPrompts(inputPrompts);
  };

  return (
    <ChatContext.Provider
      value={{
        ...value,
        inputPrompts,
        refreshInputPrompts,
        chatSessions,
        refreshChatSessions,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
};

export const useChatContext = (): ChatContextProps => {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error("useChatContext must be used within a ChatProvider");
  }
  return context;
};
