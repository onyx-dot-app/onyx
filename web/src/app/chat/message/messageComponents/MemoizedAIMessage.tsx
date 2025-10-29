import React, { useCallback, useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { FeedbackType, Message, CitationMap } from "../../interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import AIMessage from "./AIMessage";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { ProjectFile } from "@/app/chat/projects/projectsService";

interface BaseMemoizedAIMessageProps {
  rawPackets: any[];
  assistant: MinimalPersonaSnapshot;
  docs: OnyxDocument[];
  citations: CitationMap | undefined;
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  overriddenModel?: string;
  nodeId: number;
  messageId?: number;
  currentFeedback?: FeedbackType | null;
  otherMessagesCanSwitchTo: number[];
  onMessageSelection: (messageId: number) => void;
  llmManager: LlmManager | null;
  projectFiles?: ProjectFile[];
  researchType?: string | null;
}

interface InternalMemoizedAIMessageProps extends BaseMemoizedAIMessageProps {
  regenerate?: (modelOverride: LlmDescriptor) => Promise<void>;
  handleFeedbackChange: (
    newFeedback: FeedbackType | null,
    feedbackText?: string,
    predefinedFeedback?: string
  ) => Promise<void>;
}

interface MemoizedAIMessageProps extends BaseMemoizedAIMessageProps {
  createRegenerator: (regenerationRequest: {
    messageId: number;
    parentMessage: Message;
    forceSearch?: boolean;
  }) => (modelOverRide: LlmDescriptor) => Promise<void>;
  handleFeedbackChange: (
    messageId: number,
    newFeedback: FeedbackType | null,
    feedbackText?: string,
    predefinedFeedback?: string
  ) => Promise<void>;
  messageId: number | undefined;
  parentMessage?: Message;
}

const InternalMemoizedAIMessage = React.memo(
  function InternalMemoizedAIMessage({
    rawPackets,
    handleFeedbackChange,
    assistant,
    docs,
    citations,
    setPresentingDocument,
    regenerate,
    overriddenModel,
    nodeId,
    messageId,
    currentFeedback,
    otherMessagesCanSwitchTo,
    onMessageSelection,
    llmManager,
    projectFiles,
    researchType,
  }: InternalMemoizedAIMessageProps) {
    const chatState = React.useMemo(
      () => ({
        handleFeedbackChange,
        assistant,
        docs,
        userFiles: projectFiles || [],
        citations,
        setPresentingDocument,
        regenerate,
        overriddenModel,
        researchType,
      }),
      [
        handleFeedbackChange,
        assistant,
        docs,
        projectFiles,
        citations,
        setPresentingDocument,
        regenerate,
        overriddenModel,
        researchType,
      ]
    );

    return (
      <AIMessage
        rawPackets={rawPackets}
        chatState={chatState}
        nodeId={nodeId}
        messageId={messageId}
        currentFeedback={currentFeedback}
        llmManager={llmManager}
        otherMessagesCanSwitchTo={otherMessagesCanSwitchTo}
        onMessageSelection={onMessageSelection}
      />
    );
  }
);

export const MemoizedAIMessage = ({
  rawPackets,
  handleFeedbackChange,
  assistant,
  docs,
  citations,
  setPresentingDocument,
  createRegenerator,
  overriddenModel,
  nodeId,
  messageId,
  currentFeedback,
  parentMessage,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  llmManager,
  projectFiles,
  researchType,
}: MemoizedAIMessageProps) => {
  const regenerate = useMemo(() => {
    if (messageId === undefined) {
      return undefined;
    }

    if (parentMessage === undefined) {
      return undefined;
    }

    return (modelOverride: LlmDescriptor) => {
      return createRegenerator({
        messageId: messageId,
        parentMessage: parentMessage,
      })(modelOverride);
    };
  }, [messageId, parentMessage, createRegenerator]);

  // Wrap handleFeedbackChange to pass messageId
  const wrappedHandleFeedbackChange = useCallback(
    async (
      newFeedback: FeedbackType | null,
      feedbackText?: string,
      predefinedFeedback?: string
    ) => {
      if (messageId === undefined) {
        console.error("Message has no messageId");
        return;
      }
      return handleFeedbackChange(
        messageId,
        newFeedback,
        feedbackText,
        predefinedFeedback
      );
    },
    [handleFeedbackChange, messageId]
  );

  return (
    <InternalMemoizedAIMessage
      rawPackets={rawPackets}
      handleFeedbackChange={wrappedHandleFeedbackChange}
      assistant={assistant}
      docs={docs}
      citations={citations}
      setPresentingDocument={setPresentingDocument}
      regenerate={regenerate}
      overriddenModel={overriddenModel}
      nodeId={nodeId}
      messageId={messageId}
      currentFeedback={currentFeedback}
      otherMessagesCanSwitchTo={otherMessagesCanSwitchTo}
      onMessageSelection={onMessageSelection}
      llmManager={llmManager}
      projectFiles={projectFiles}
      researchType={researchType}
    />
  );
};
