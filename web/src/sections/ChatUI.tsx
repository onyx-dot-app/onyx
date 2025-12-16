"use client";

import React, {
  ForwardedRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgChevronDown from "@/icons/chevron-down";
import { Message } from "@/app/chat/interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import HumanMessage from "@/app/chat/message/HumanMessage";
import { ErrorBanner } from "@/app/chat/message/Resubmit";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { FileDescriptor } from "@/app/chat/interfaces";
import AIMessage from "@/app/chat/message/messageComponents/AIMessage";
import { ProjectFile } from "@/app/chat/projects/projectsService";
import { useScrollonStream } from "@/app/chat/services/lib";
import useScreenSize from "@/hooks/useScreenSize";
import {
  useChatPageLayout,
  useCurrentChatState,
  useCurrentMessageTree,
  useUncaughtError,
} from "@/app/chat/stores/useChatSessionStore";
import useChatSessions from "@/hooks/useChatSessions";
import { useDeepResearchToggle } from "../app/chat/hooks/useDeepResearchToggle";
import { useUser } from "@/components/user/UserProvider";
import { HORIZON_DISTANCE_PX } from "@/lib/constants";
import Spacer from "@/refresh-components/Spacer";

export interface ChatUIHandle {
  scrollToBottom: () => boolean;
  scrollBy: (delta: number) => void;
}

export interface ChatUIProps {
  liveAssistant: MinimalPersonaSnapshot | undefined;
  llmManager: LlmManager;
  currentMessageFiles: ProjectFile[];
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  onSubmit: (args: {
    message: string;
    messageIdToResend?: number;
    currentMessageFiles: ProjectFile[];
    useAgentSearch: boolean;
    modelOverride?: LlmDescriptor;
    regenerationRequest?: {
      messageId: number;
      parentMessage: Message;
      forceSearch?: boolean;
    };
    forceSearch?: boolean;
    queryOverride?: string;
    isSeededChat?: boolean;
    overrideFileDescriptors?: FileDescriptor[];
  }) => Promise<void>;
  onMessageSelection: (nodeId: number) => void;
  stopGenerating: () => void;
  handleResubmitLastMessage: () => void;
}

const ChatUI = React.forwardRef(
  (
    {
      liveAssistant,
      llmManager,
      currentMessageFiles,
      setPresentingDocument,
      onSubmit,
      onMessageSelection,
      stopGenerating,
      handleResubmitLastMessage,
    }: ChatUIProps,
    ref: ForwardedRef<ChatUIHandle>
  ) => {
    const { user } = useUser();
    const { currentChatSessionId } = useChatSessions();
    const { deepResearchEnabled } = useDeepResearchToggle({
      chatSessionId: currentChatSessionId,
      assistantId: liveAssistant?.id,
    });
    const { isMobile } = useScreenSize();
    const { messageHistory: messages, loadingError: loadError } =
      useChatPageLayout();
    const error = useUncaughtError();
    const messageTree = useCurrentMessageTree();
    const currentChatState = useCurrentChatState();

    // Stable fallbacks to avoid changing prop identities on each render
    const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
    const emptyChildrenIds = useMemo<number[]>(() => [], []);

    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const endDivRef = useRef<HTMLDivElement>(null);
    const scrollDist = useRef<number>(0);
    const [aboveHorizon, setAboveHorizon] = useState(false);
    const debounceNumber = 100;

    const createRegenerator = useCallback(
      (regenerationRequest: {
        messageId: number;
        parentMessage: Message;
        forceSearch?: boolean;
      }) => {
        return async function (modelOverride: LlmDescriptor) {
          return await onSubmit({
            message: regenerationRequest.parentMessage.message,
            currentMessageFiles,
            useAgentSearch: deepResearchEnabled,
            modelOverride,
            messageIdToResend: regenerationRequest.parentMessage.messageId,
            regenerationRequest,
            forceSearch: regenerationRequest.forceSearch,
          });
        };
      },
      [onSubmit, deepResearchEnabled, currentMessageFiles]
    );

    const handleEditWithMessageId = useCallback(
      (editedContent: string, msgId: number) => {
        onSubmit({
          message: editedContent,
          messageIdToResend: msgId,
          currentMessageFiles: [],
          useAgentSearch: deepResearchEnabled,
        });
      },
      [onSubmit, deepResearchEnabled]
    );

    const handleScroll = useCallback(() => {
      const container = scrollContainerRef.current;
      if (!container) return;

      const distanceFromBottom =
        container.scrollHeight - (container.scrollTop + container.clientHeight);

      scrollDist.current = distanceFromBottom;
      setAboveHorizon(distanceFromBottom > HORIZON_DISTANCE_PX);
    }, []);

    const scrollToBottom = useCallback(() => {
      if (!endDivRef.current) return false;
      endDivRef.current.scrollIntoView({ behavior: "smooth" });
      return true;
    }, []);

    const scrollBy = useCallback((delta: number) => {
      if (!scrollContainerRef.current) return;
      scrollContainerRef.current.scrollBy({
        behavior: "smooth",
        top: delta,
      });
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        scrollToBottom,
        scrollBy,
      }),
      [scrollToBottom, scrollBy]
    );

    useScrollonStream({
      chatState: currentChatState,
      scrollableDivRef: scrollContainerRef,
      scrollDist,
      endDivRef,
      debounceNumber,
      mobile: isMobile,
      enableAutoScroll: user?.preferences.auto_scroll,
    });

    useEffect(() => {
      if (!scrollContainerRef.current) return;
      scrollContainerRef.current.scrollTop =
        scrollContainerRef.current.scrollHeight;
    }, [messages]);

    if (!liveAssistant) return <div className="flex-1" />;

    return (
      <div className="flex flex-col flex-1 w-full relative overflow-hidden">
        {aboveHorizon && (
          <div className="absolute bottom-0 z-[1000000] left-1/2 -translate-x-1/2">
            <IconButton icon={SvgChevronDown} onClick={scrollToBottom} />

            <Spacer />
          </div>
        )}

        <div
          key={currentChatSessionId}
          ref={scrollContainerRef}
          className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden default-scrollbar"
          onScroll={handleScroll}
        >
          {messages.map((message, i) => {
            const messageReactComponentKey = `message-${message.nodeId}`;
            const parentMessage = message.parentNodeId
              ? messageTree?.get(message.parentNodeId)
              : null;

            if (message.type === "user") {
              const nextMessage =
                messages.length > i + 1 ? messages[i + 1] : null;

              return (
                <div
                  id={messageReactComponentKey}
                  key={messageReactComponentKey}
                >
                  <HumanMessage
                    disableSwitchingForStreaming={
                      (nextMessage && nextMessage.is_generating) || false
                    }
                    stopGenerating={stopGenerating}
                    content={message.message}
                    files={message.files}
                    messageId={message.messageId}
                    onEdit={(editedContent) => {
                      if (
                        message.messageId !== undefined &&
                        message.messageId !== null
                      ) {
                        handleEditWithMessageId(
                          editedContent,
                          message.messageId
                        );
                      }
                    }}
                    otherMessagesCanSwitchTo={
                      parentMessage?.childrenNodeIds ?? emptyChildrenIds
                    }
                    onMessageSelection={onMessageSelection}
                  />
                </div>
              );
            } else if (message.type === "assistant") {
              if ((error || loadError) && i === messages.length - 1) {
                return (
                  <div
                    key={`error-${message.nodeId}`}
                    className="max-w-message-max mx-auto"
                  >
                    <ErrorBanner
                      resubmit={handleResubmitLastMessage}
                      error={error || loadError || ""}
                    />
                  </div>
                );
              }

              // NOTE: it's fine to use the previous entry in messageHistory
              // since this is a "parsed" version of the message tree
              // so the previous message is guaranteed to be the parent of the current message
              const previousMessage = i !== 0 ? messages[i - 1] : null;
              const regenerate =
                message.messageId !== undefined && previousMessage
                  ? createRegenerator({
                      messageId: message.messageId,
                      parentMessage: previousMessage,
                    })
                  : undefined;
              const chatStateData = {
                assistant: liveAssistant,
                docs: message.documents ?? emptyDocs,
                citations: message.citations,
                setPresentingDocument,
                regenerate,
                overriddenModel: llmManager.currentLlm?.modelName,
                researchType: message.researchType,
              };
              return (
                <div
                  id={`message-${message.nodeId}`}
                  key={messageReactComponentKey}
                >
                  <AIMessage
                    rawPackets={message.packets}
                    chatState={chatStateData}
                    nodeId={message.nodeId}
                    messageId={message.messageId}
                    currentFeedback={message.currentFeedback}
                    llmManager={llmManager}
                    otherMessagesCanSwitchTo={
                      parentMessage?.childrenNodeIds ?? emptyChildrenIds
                    }
                    onMessageSelection={onMessageSelection}
                  />
                </div>
              );
            }
          })}

          {(((error !== null || loadError !== null) &&
            messages[messages.length - 1]?.type === "user") ||
            messages[messages.length - 1]?.type === "error") && (
            <div className="max-w-message-max mx-auto">
              <ErrorBanner
                resubmit={handleResubmitLastMessage}
                error={error || loadError || ""}
              />
            </div>
          )}

          <div ref={endDivRef} />
        </div>
      </div>
    );
  }
);
ChatUI.displayName = "ChatUI";

export default ChatUI;
