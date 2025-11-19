"use client";

import { useCallback } from "react";
import { useChatSessionStore } from "@/app/chat/stores/useChatSessionStore";
import { FeedbackType } from "@/app/chat/interfaces";
import {
  handleChatFeedback,
  removeChatFeedback,
} from "@/app/chat/services/lib";
import { getMessageByMessageId } from "@/app/chat/services/messageTree";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface UseFeedbackControllerProps {
  setPopup: (popup: PopupSpec | null) => void;
}

export function useFeedbackController({
  setPopup,
}: UseFeedbackControllerProps) {
  const updateCurrentMessageFeedback = useChatSessionStore(
    (state) => state.updateCurrentMessageFeedback
  );

  const handleFeedbackChange = useCallback(
    async (
      messageId: number,
      newFeedback: FeedbackType | null,
      feedbackText?: string,
      predefinedFeedback?: string
    ) => {
      // Get current feedback state for rollback on error
      const { currentSessionId, sessions } = useChatSessionStore.getState();
      const messageTree = currentSessionId
        ? sessions.get(currentSessionId)?.messageTree
        : undefined;
      const previousFeedback = messageTree
        ? getMessageByMessageId(messageTree, messageId)?.currentFeedback ?? null
        : null;

      // Optimistically update the UI
      updateCurrentMessageFeedback(messageId, newFeedback);

      try {
        if (newFeedback === null) {
          // Remove feedback
          const response = await removeChatFeedback(messageId);
          if (!response.ok) {
            // Rollback on error
            updateCurrentMessageFeedback(messageId, previousFeedback);
            const errorData = await response.json();
            setPopup({
              message: `Failed to remove feedback - ${
                errorData.detail || errorData.message
              }`,
              type: "error",
            });
          }
        } else {
          // Add/update feedback
          const response = await handleChatFeedback(
            messageId,
            newFeedback,
            feedbackText || "",
            predefinedFeedback
          );
          if (!response.ok) {
            // Rollback on error
            updateCurrentMessageFeedback(messageId, previousFeedback);
            const errorData = await response.json();
            setPopup({
              message: `Failed to submit feedback - ${
                errorData.detail || errorData.message
              }`,
              type: "error",
            });
          }
        }
      } catch (error) {
        // Rollback on network error
        updateCurrentMessageFeedback(messageId, previousFeedback);
        setPopup({
          message: "Failed to submit feedback - network error",
          type: "error",
        });
      }
    },
    [updateCurrentMessageFeedback, setPopup]
  );

  return { handleFeedbackChange };
}
