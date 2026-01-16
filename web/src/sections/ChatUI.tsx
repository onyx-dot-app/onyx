"use client";

import React, { ForwardedRef, useImperativeHandle, useRef } from "react";
import { Message } from "@/app/chat/interfaces";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { ProjectFile } from "@/app/chat/projects/projectsService";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useLoadingError,
  useUncaughtError,
} from "@/app/chat/stores/useChatSessionStore";
import useChatSessions from "@/hooks/useChatSessions";
import { useUser } from "@/components/user/UserProvider";
import ChatScrollContainer, {
  ChatScrollContainerHandle,
} from "@/components/chat/ChatScrollContainer";
import MessageList from "@/components/chat/MessageList";

export interface ChatUIHandle {
  scrollToBottom: () => boolean;
}

export interface ChatUIProps {
  liveAssistant: MinimalPersonaSnapshot | undefined;
  llmManager: LlmManager;
  currentMessageFiles: ProjectFile[];
  deepResearchEnabled: boolean;
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  onSubmit: (args: {
    message: string;
    messageIdToResend?: number;
    currentMessageFiles: ProjectFile[];
    deepResearch: boolean;
    modelOverride?: LlmDescriptor;
    regenerationRequest?: {
      messageId: number;
      parentMessage: Message;
      forceSearch?: boolean;
    };
    forceSearch?: boolean;
    queryOverride?: string;
    isSeededChat?: boolean;
  }) => Promise<void>;
  onMessageSelection: (nodeId: number) => void;
  stopGenerating: () => void;
  handleResubmitLastMessage: () => void;
  onScrollButtonVisibilityChange?: (visible: boolean) => void;
}

const ChatUI = React.memo(
  React.forwardRef(
    (
      {
        liveAssistant,
        llmManager,
        currentMessageFiles,
        deepResearchEnabled,
        setPresentingDocument,
        onSubmit,
        onMessageSelection,
        stopGenerating,
        handleResubmitLastMessage,
        onScrollButtonVisibilityChange,
      }: ChatUIProps,
      ref: ForwardedRef<ChatUIHandle>
    ) => {
      const { user } = useUser();
      const { currentChatSessionId } = useChatSessions();
      const loadError = useLoadingError();
      const messages = useCurrentMessageHistory();
      const error = useUncaughtError();
      const messageTree = useCurrentMessageTree();
      const currentChatState = useCurrentChatState();

      const scrollContainerRef = useRef<ChatScrollContainerHandle>(null);

      const autoScrollEnabled = user?.preferences.auto_scroll !== false;
      const isStreaming = currentChatState === "streaming";

      // Determine anchor: second-to-last message (last user message before current response)
      const anchorMessage = messages.at(-2) ?? messages[0];
      const anchorNodeId = anchorMessage?.nodeId;
      const anchorSelector = anchorNodeId
        ? `#message-${anchorNodeId}`
        : undefined;

      // Expose scrollToBottom via ref
      useImperativeHandle(
        ref,
        () => ({
          scrollToBottom: () => {
            scrollContainerRef.current?.scrollToBottom();
            return true;
          },
        }),
        []
      );

      if (!liveAssistant) return <div className="flex-1" />;

      return (
        <ChatScrollContainer
          ref={scrollContainerRef}
          sessionId={currentChatSessionId ?? undefined}
          anchorSelector={anchorSelector}
          autoScroll={autoScrollEnabled}
          isStreaming={isStreaming}
          onScrollButtonVisibilityChange={onScrollButtonVisibilityChange}
        >
          <MessageList
            messages={messages}
            messageTree={messageTree}
            liveAssistant={liveAssistant}
            llmManager={llmManager}
            setPresentingDocument={setPresentingDocument}
            onMessageSelection={onMessageSelection}
            stopGenerating={stopGenerating}
            onSubmit={onSubmit}
            deepResearchEnabled={deepResearchEnabled}
            currentMessageFiles={currentMessageFiles}
            error={error}
            loadError={loadError}
            onResubmit={handleResubmitLastMessage}
            anchorNodeId={anchorNodeId}
          />
        </ChatScrollContainer>
      );
    }
  )
);

ChatUI.displayName = "ChatUI";

export default ChatUI;
