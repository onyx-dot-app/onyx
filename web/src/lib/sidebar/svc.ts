"use client";

import { toast } from "@/hooks/useToast";
import { moveChatSession } from "@/lib/projects/svc";
import type { MoveOperationParams } from "@/lib/sidebar/utils";

/**
 * Moves a chat session to the given project, then refreshes all stale data.
 *
 * On success, the function resolves once both `refreshChatSessions` and the
 * appropriate project refresh (current-project details or full project list)
 * have settled. On failure it shows an error toast and re-throws so the
 * caller can handle the error (e.g. to dismiss a loading state).
 */
export const handleMoveOperation = async ({
  chatSession,
  targetProjectId,
  refreshChatSessions,
  refreshCurrentProjectDetails,
  fetchProjects,
  currentProjectId,
}: MoveOperationParams) => {
  try {
    await moveChatSession(targetProjectId, chatSession.id);
    const projectRefreshPromise = currentProjectId
      ? refreshCurrentProjectDetails()
      : fetchProjects();
    await Promise.all([refreshChatSessions(), projectRefreshPromise]);
  } catch (error) {
    console.error("Failed to perform move operation:", error);
    toast.error("Failed to move chat. Please try again.");
    throw error;
  }
};
