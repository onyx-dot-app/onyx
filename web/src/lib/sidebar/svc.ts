"use client";

import { toast } from "@/hooks/useToast";
import { moveChatSession } from "@/app/app/projects/projectsService";
import type { MoveOperationParams } from "@/lib/sidebar/utils";

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
