"use client";

import { useCallback } from "react";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { FeedbackType } from "@/app/app/interfaces";
import { handleChatFeedback, removeChatFeedback } from "@/app/app/services/lib";
import { getMessageByMessageId } from "@/app/app/services/messageTree";
import { toast } from "@/hooks/useToast";

/**
 * Hook for managing chat message feedback (like/dislike)
 *
 * Provides optimistic UI updates with automatic rollback on errors.
 * Handles both adding/updating feedback and removing existing feedback.
 *
 * @returns Object containing:
 *   - handleFeedbackChange: Function to submit feedback changes
 *
 * @example
 * ```tsx
 * const { handleFeedbackChange } = useFeedbackController();
 *
 * // Add positive feedback
 * await handleFeedbackChange(messageId, "like", "Great response!");
 *
 * // Remove feedback
 * await handleFeedbackChange(messageId, null);
 * ```
 */
export default function useFeedbackController() {
  const updateCurrentMessageFeedback = useChatSessionStore(
    (state) => state.updateCurrentMessageFeedback
  );

  const handleFeedbackChange = useCallback(
    async (
      messageId: number,
      newFeedback: FeedbackType | null,
      feedbackText?: string,
      predefinedFeedback?: string
    ): Promise<boolean> => {
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
            toast.error(
              `Failed to remove feedback - ${
                errorData.detail || errorData.message
              }`
            );
            return false;
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
            toast.error(
              `Failed to submit feedback - ${
                errorData.detail || errorData.message
              }`
            );
            return false;
          }
        }
        return true;
      } catch (error) {
        // Rollback on network error
        updateCurrentMessageFeedback(messageId, previousFeedback);
        toast.error("Failed to submit feedback - network error");
        return false;
      }
    },
    [updateCurrentMessageFeedback]
  );

  return { handleFeedbackChange };
}
