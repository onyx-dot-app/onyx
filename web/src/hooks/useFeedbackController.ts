"use client";

import { useCallback } from "react";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { FeedbackType } from "@/app/app/interfaces";
import { handleChatFeedback, removeChatFeedback } from "@/app/app/services/lib";
import { getMessageByMessageId } from "@/app/app/services/messageTree";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface UseFeedbackControllerProps {
  /** Function to display error messages to the user */
  setPopup: (popup: PopupSpec | null) => void;
}

/**
 * Hook for managing chat message feedback (like/dislike)
 *
 * Provides optimistic UI updates with automatic rollback on errors.
 * Handles both adding/updating feedback and removing existing feedback.
 *
 * @param props - Configuration object
 * @param props.setPopup - Function to display error popups to the user
 *
 * @returns Object containing:
 *   - handleFeedbackChange: Function to submit feedback changes
 *
 * @example
 * ```tsx
 * const { popup, setPopup } = usePopup();
 * const { handleFeedbackChange } = useFeedbackController({ setPopup });
 *
 * // Add positive feedback
 * await handleFeedbackChange(messageId, "like", "Great response!");
 *
 * // Add negative feedback with predefined option
 * await handleFeedbackChange(
 *   messageId,
 *   "dislike",
 *   "Not helpful",
 *   "Retrieved documents were not relevant"
 * );
 *
 * // Remove feedback
 * await handleFeedbackChange(messageId, null);
 * ```
 */
export default function useFeedbackController({
  setPopup,
}: UseFeedbackControllerProps) {
  const updateCurrentMessageFeedback = useChatSessionStore(
    (state) => state.updateCurrentMessageFeedback
  );

  /**
   * Submit feedback for a chat message
   *
   * Optimistically updates the UI immediately, then sends the request to the server.
   * Automatically rolls back the UI change if the server request fails.
   *
   * @param messageId - ID of the message to provide feedback for
   * @param newFeedback - Type of feedback ("like", "dislike", or null to remove)
   * @param feedbackText - Optional text explaining the feedback
   * @param predefinedFeedback - Optional predefined feedback category/reason
   *
   * @returns Promise<boolean> - true if feedback was successfully submitted, false otherwise
   *
   * @example
   * ```tsx
   * // Submit positive feedback
   * const success = await handleFeedbackChange(123, "like", "Very helpful!");
   *
   * // Submit negative feedback with predefined reason
   * const success = await handleFeedbackChange(
   *   123,
   *   "dislike",
   *   "The sources were incorrect",
   *   "Cited source had incorrect information"
   * );
   *
   * // Remove existing feedback
   * const success = await handleFeedbackChange(123, null);
   * ```
   */
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
            setPopup({
              message: `Failed to remove feedback - ${
                errorData.detail || errorData.message
              }`,
              type: "error",
            });
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
            setPopup({
              message: `Failed to submit feedback - ${
                errorData.detail || errorData.message
              }`,
              type: "error",
            });
            return false;
          }
        }
        return true;
      } catch (error) {
        // Rollback on network error
        updateCurrentMessageFeedback(messageId, previousFeedback);
        setPopup({
          message: "Failed to submit feedback - network error",
          type: "error",
        });
        return false;
      }
    },
    [updateCurrentMessageFeedback, setPopup]
  );

  return { handleFeedbackChange };
}
