"use client";

import React, { createContext, useContext, useState } from "react";
import { CCPairBasicInfo, DocumentSet, Tag, ValidSources } from "@/lib/types";
import { ChatSession, InputPrompt } from "@/app/chat/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { Folder } from "@/app/chat/folders/interfaces";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";

interface ChatContextProps {
  chatSessions: ChatSession[];
  sidebarInitiallyVisible: boolean;
  availableSources: ValidSources[];
  ccPairs: CCPairBasicInfo[];
  tags: Tag[];
  documentSets: DocumentSet[];
  availableDocumentSets: DocumentSet[];
  availableTags: Tag[];
  llmProviders: LLMProviderDescriptor[];
  folders: Folder[];
  openedFolders: Record<string, boolean>;
  shouldShowWelcomeModal?: boolean;
  shouldDisplaySourcesIncompleteModal?: boolean;
  defaultAssistantId?: number;
  refreshChatSessions: () => Promise<void>;
  reorderFolders: (displayPriorityMap: Record<number, number>) => void;
  refreshFolders: () => Promise<void>;
  refreshInputPrompts: () => Promise<void>;
  inputPrompts: InputPrompt[];
  proSearchToggled: boolean;
}

const ChatContext = createContext<ChatContextProps | undefined>(undefined);

// We use Omit to exclude 'refreshChatSessions' from the value prop type
// because we're defining it within the component
export const ChatProvider: React.FC<{
  value: Omit<
    ChatContextProps,
    | "refreshChatSessions"
    | "refreshAvailableAssistants"
    | "reorderFolders"
    | "refreshFolders"
    | "refreshInputPrompts"
  >;
  children: React.ReactNode;
}> = ({ value, children }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [inputPrompts, setInputPrompts] = useState(value?.inputPrompts || []);
  const [chatSessions, setChatSessions] = useState(value?.chatSessions || []);
  const [folders, setFolders] = useState(value?.folders || []);

  const reorderFolders = (displayPriorityMap: Record<number, number>) => {
    setFolders(
      folders.map((folder) => {
        if (folder.folder_id) {
          folder.display_priority = displayPriorityMap[folder.folder_id];
        }
        return folder;
      })
    );
  };

  const refreshChatSessions = async () => {
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
        router.replace("/chat");
      }
    } catch (error) {
      console.error("Error refreshing chat sessions:", error);
    }
  };
  const refreshFolders = async () => {
    const response = await fetch("/api/folder");
    if (!response.ok) throw new Error("Failed to fetch folders");
    const { folders } = await response.json();
    setFolders(folders);
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
        folders,
        reorderFolders,
        refreshChatSessions,
        refreshFolders,
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
