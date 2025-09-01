import React, { useCallback, useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { FeedbackType, Message, CitationMap } from "../../interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { AIMessage } from "./AIMessage";
import { LlmDescriptor } from "@/lib/hooks";

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
}

interface InternalMemoizedAIMessageProps extends BaseMemoizedAIMessageProps {
  regenerate: (modelOverRide: LlmDescriptor) => Promise<void>;
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
  parentMessage: Message;
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
}: InternalMemoizedAIMessageProps) {
  return (
    <AIMessage
      rawPackets={rawPackets}
      chatState={{
        handleFeedback,
        assistant,
        docs,
        userFiles: [],
        citations,
        setPresentingDocument,
        regenerate,
        overriddenModel,
      }}
      nodeId={nodeId}
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
}: MemoizedAIMessageProps) => {
  const regenerate = useMemo(
    () => (modelOverRide: LlmDescriptor) =>
      createRegenerator({
        messageId: messageId!,
        parentMessage: parentMessage,
      })(modelOverRide),
    [messageId, parentMessage]
  );

  const handleFeedback = useCallback(
    (feedback: FeedbackType) => {
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
    />
  );
};
