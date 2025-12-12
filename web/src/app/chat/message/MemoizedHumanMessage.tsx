import React, { RefObject, useCallback } from "react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { FileDescriptor } from "@/app/chat/interfaces";
import HumanMessage from "./HumanMessage";

interface BaseMemoizedHumanMessageProps {
  content: string;
  files?: FileDescriptor[];
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (messageId: number) => void;
  shared?: boolean;
  stopGenerating?: () => void;
  disableSwitchingForStreaming?: boolean;
  bubbleRef?: RefObject<HTMLDivElement | null>;
}

interface InternalMemoizedHumanMessageProps
  extends BaseMemoizedHumanMessageProps {
  onEdit: (editedContent: string) => void;
}

interface MemoizedHumanMessageProps extends BaseMemoizedHumanMessageProps {
  handleEditWithMessageId: (editedContent: string, messageId: number) => void;
}

const _MemoizedHumanMessage = React.memo(function _MemoizedHumanMessage({
  content,
  files,
  messageId,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  shared,
  stopGenerating,
  disableSwitchingForStreaming,
  onEdit,
  bubbleRef,
}: InternalMemoizedHumanMessageProps) {
  return (
    <HumanMessage
      content={content}
      files={files}
      messageId={messageId ?? undefined}
      otherMessagesCanSwitchTo={otherMessagesCanSwitchTo}
      onMessageSelection={onMessageSelection}
      shared={shared}
      stopGenerating={stopGenerating}
      disableSwitchingForStreaming={disableSwitchingForStreaming}
      onEdit={onEdit}
      bubbleRef={bubbleRef}
    />
  );
});

export const MemoizedHumanMessage = ({
  content,
  files,
  messageId,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  shared,
  stopGenerating,
  disableSwitchingForStreaming,
  handleEditWithMessageId,
  bubbleRef,
}: MemoizedHumanMessageProps) => {
  const onEdit = useCallback(
    (editedContent: string) => {
      if (messageId === null || messageId === undefined) {
        console.warn(
          "No message id specified; cannot edit an undefined message"
        );
        return;
      }

      handleEditWithMessageId(editedContent, messageId);
    },
    [handleEditWithMessageId, messageId]
  );

  return (
    <_MemoizedHumanMessage
      content={content}
      files={files}
      messageId={messageId}
      otherMessagesCanSwitchTo={otherMessagesCanSwitchTo}
      onMessageSelection={onMessageSelection}
      shared={shared}
      stopGenerating={stopGenerating}
      disableSwitchingForStreaming={disableSwitchingForStreaming}
      onEdit={onEdit}
      bubbleRef={bubbleRef}
    />
  );
};
