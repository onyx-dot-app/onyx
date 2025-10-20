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
  otherMessagesCanSwitchTo: number[];
  onMessageSelection: (messageId: number) => void;
  llmManager: LlmManager | null;
  projectFiles?: ProjectFile[];
  researchType?: string | null;
}

interface InternalMemoizedAIMessageProps extends BaseMemoizedAIMessageProps {
  regenerate?: (modelOverride: LlmDescriptor) => Promise<void>;
  handleFeedback: (feedback: FeedbackType) => void;
}

interface MemoizedAIMessageProps extends BaseMemoizedAIMessageProps {
  createRegenerator: (regenerationRequest: {
    messageId: number;
    parentMessage: Message;
    forceSearch?: boolean;
  }) => (modelOverRide: LlmDescriptor) => Promise<void>;
  handleFeedbackWithMessageId: (
    feedback: FeedbackType,
    messageId: number
  ) => void;
  messageId: number | undefined;
  parentMessage?: Message;
}

const _MemoizedAIMessage = React.memo(function _MemoizedAIMessage({
  rawPackets,
  handleFeedback,
  assistant,
  docs,
  citations,
  setPresentingDocument,
  regenerate,
  overriddenModel,
  nodeId,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  llmManager,
  projectFiles,
  researchType,
}: InternalMemoizedAIMessageProps) {
  return (
    <AIMessage
      rawPackets={rawPackets}
      chatState={{
        handleFeedback,
        assistant,
        docs,
        userFiles: projectFiles || [],
        citations,
        setPresentingDocument,
        regenerate,
        overriddenModel,
        researchType,
      }}
      nodeId={nodeId}
      llmManager={llmManager}
      otherMessagesCanSwitchTo={otherMessagesCanSwitchTo}
      onMessageSelection={onMessageSelection}
    />
  );
});

export const MemoizedAIMessage = ({
  rawPackets,
  handleFeedbackWithMessageId,
  assistant,
  docs,
  citations,
  setPresentingDocument,
  createRegenerator,
  overriddenModel,
  nodeId,
  messageId,
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

  const handleFeedback = useCallback(
    (feedback: FeedbackType) => {
      if (messageId === undefined) {
        console.error("Message has no messageId", nodeId);
        return;
      }
      handleFeedbackWithMessageId(feedback, messageId!);
    },
    [handleFeedbackWithMessageId, messageId]
  );

  return (
    <_MemoizedAIMessage
      rawPackets={rawPackets}
      handleFeedback={handleFeedback}
      assistant={assistant}
      docs={docs}
      citations={citations}
      setPresentingDocument={setPresentingDocument}
      regenerate={regenerate}
      overriddenModel={overriddenModel}
      nodeId={nodeId}
      otherMessagesCanSwitchTo={otherMessagesCanSwitchTo}
      onMessageSelection={onMessageSelection}
      llmManager={llmManager}
      projectFiles={projectFiles}
      researchType={researchType}
    />
  );
};
