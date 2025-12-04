import React, { useCallback, useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { FeedbackType, Message, CitationMap } from "../../interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import AIMessage from "./AIMessage";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { ProjectFile } from "@/app/chat/projects/projectsService";
import { ModelResponse } from "./ModelResponseTabs";

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
  // Multi-model responses
  modelResponses?: ModelResponse[];
}

interface InternalMemoizedAIMessageProps extends BaseMemoizedAIMessageProps {
  regenerate?: (modelOverride: LlmDescriptor) => Promise<void>;
}

interface MemoizedAIMessageProps extends BaseMemoizedAIMessageProps {
  createRegenerator: (regenerationRequest: {
    messageId: number;
    parentMessage: Message;
    forceSearch?: boolean;
  }) => (modelOverRide: LlmDescriptor) => Promise<void>;
  messageId: number | undefined;
  parentMessage?: Message;
}

const InternalMemoizedAIMessage = React.memo(
  function InternalMemoizedAIMessage({
    rawPackets,
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
    modelResponses,
  }: InternalMemoizedAIMessageProps) {
    const chatState = React.useMemo(
      () => ({
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
        modelResponses={modelResponses}
      />
    );
  }
);

export const MemoizedAIMessage = ({
  rawPackets,
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
  modelResponses,
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

  return (
    <InternalMemoizedAIMessage
      rawPackets={rawPackets}
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
      modelResponses={modelResponses}
    />
  );
};
