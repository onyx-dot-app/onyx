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
import { ChatState, Message } from "@/app/chat/interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import HumanMessage from "@/app/chat/message/HumanMessage";
import { ErrorBanner } from "@/app/chat/message/Resubmit";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { EnterpriseSettings } from "@/app/admin/settings/interfaces";
import { FileDescriptor } from "@/app/chat/interfaces";
import AIMessage from "@/app/chat/message/messageComponents/AIMessage";
import { ProjectFile } from "@/app/chat/projects/projectsService";
import { cn } from "@/lib/utils";
import { useScrollonStream } from "@/app/chat/services/lib";

export interface MessagesDisplayHandle {
  scrollToBottom: (fast?: boolean) => boolean;
  scrollBy: (delta: number) => void;
}

export interface MessagesDisplayProps {
  messageHistory: Message[];
  completeMessageTree: Map<number, Message> | null | undefined;
  liveAssistant: MinimalPersonaSnapshot | undefined;
  llmManager: LlmManager;
  deepResearchEnabled: boolean;
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
  uncaughtError: string | null;
  loadingError: string | null;
  handleResubmitLastMessage: () => void;
  autoScrollEnabled: boolean;
  chatState: ChatState;
  isMobile?: boolean;
  hasPerformedInitialScroll: boolean;
  chatSessionId: string | null;
}

const MessagesDisplay = React.forwardRef(
  (
    {
      messageHistory,
      completeMessageTree,
      liveAssistant,
      llmManager,
      deepResearchEnabled,
      currentMessageFiles,
      setPresentingDocument,
      onSubmit,
      onMessageSelection,
      stopGenerating,
      uncaughtError,
      loadingError,
      handleResubmitLastMessage,
      autoScrollEnabled,
      chatState,
      isMobile,
      hasPerformedInitialScroll,
      chatSessionId,
    }: MessagesDisplayProps,
    ref: ForwardedRef<MessagesDisplayHandle>
  ) => {
    // Stable fallbacks to avoid changing prop identities on each render
    const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
    const emptyChildrenIds = useMemo<number[]>(() => [], []);
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const endDivRef = useRef<HTMLDivElement>(null);
    const lastMessageRef = useRef<HTMLDivElement>(null);
    const scrollDist = useRef<number>(0);
    const [aboveHorizon, setAboveHorizon] = useState(false);
    const debounceNumber = 100;
    const HORIZON_DISTANCE = 800;

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
      setAboveHorizon(distanceFromBottom > HORIZON_DISTANCE);
    }, []);

    useEffect(() => {
      scrollDist.current = 0;
      setAboveHorizon(false);
    }, [chatSessionId]);

    const scrollToBottom = useCallback((fast?: boolean) => {
      if (!endDivRef.current) return false;

      endDivRef.current.scrollIntoView({
        behavior: fast ? "auto" : "smooth",
      });
      return true;
    }, []);

    const scrollBy = useCallback((delta: number) => {
      if (!scrollContainerRef.current) return;
      scrollContainerRef.current.scrollBy({
        left: 0,
        top: delta,
        behavior: "smooth",
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
      chatState,
      scrollableDivRef: scrollContainerRef,
      scrollDist,
      endDivRef,
      debounceNumber,
      mobile: isMobile,
      enableAutoScroll: autoScrollEnabled,
    });

    if (!liveAssistant) {
      return null;
    }

    return (
      <div
        key={chatSessionId}
        ref={scrollContainerRef}
        className={cn(
          "overflow-y-auto overflow-x-hidden default-scrollbar",
          !hasPerformedInitialScroll && "hidden"
        )}
        onScroll={handleScroll}
      >
        {aboveHorizon && (
          <div className="absolute bottom-0 z-100 w-full pointer-events-auto mx-auto flex justify-center">
            <IconButton
              icon={SvgChevronDown}
              onClick={() => scrollToBottom()}
            />
          </div>
        )}

        {messageHistory.map((message, i) => {
          const messageTree = completeMessageTree;
          const messageReactComponentKey = `message-${message.nodeId}`;
          const parentMessage = message.parentNodeId
            ? messageTree?.get(message.parentNodeId)
            : null;

          if (message.type === "user") {
            const nextMessage =
              messageHistory.length > i + 1 ? messageHistory[i + 1] : null;

            return (
              <div id={messageReactComponentKey} key={messageReactComponentKey}>
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
                      handleEditWithMessageId(editedContent, message.messageId);
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
            if (
              (uncaughtError || loadingError) &&
              i === messageHistory.length - 1
            ) {
              return (
                <div
                  key={`error-${message.nodeId}`}
                  className="max-w-message-max mx-auto"
                >
                  <ErrorBanner
                    resubmit={handleResubmitLastMessage}
                    error={uncaughtError || loadingError || ""}
                  />
                </div>
              );
            }

            // NOTE: it's fine to use the previous entry in messageHistory
            // since this is a "parsed" version of the message tree
            // so the previous message is guaranteed to be the parent of the current message
            const previousMessage = i !== 0 ? messageHistory[i - 1] : null;
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
                className="text-text"
                id={`message-${message.nodeId}`}
                key={messageReactComponentKey}
                ref={i === messageHistory.length - 1 ? lastMessageRef : null}
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

        {((uncaughtError !== null || loadingError !== null) &&
          messageHistory[messageHistory.length - 1]?.type === "user") ||
          (messageHistory[messageHistory.length - 1]?.type === "error" && (
            <div className="max-w-message-max mx-auto">
              <ErrorBanner
                resubmit={handleResubmitLastMessage}
                error={uncaughtError || loadingError || ""}
              />
            </div>
          ))}

        <div ref={endDivRef} />
      </div>
    );
  }
);
MessagesDisplay.displayName = "MessagesDisplay";

export default MessagesDisplay;
