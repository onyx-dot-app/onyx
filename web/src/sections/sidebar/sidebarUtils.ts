import { ChatSession } from "@/app/app/interfaces";
import { LOCAL_STORAGE_KEYS, DEFAULT_PERSONA_ID } from "./constants";
import { moveChatSession } from "@/app/app/projects/projectsService";
import { toast } from "@/hooks/useToast";

export const shouldShowMoveModal = (chatSession: ChatSession): boolean => {
  const hideModal =
    typeof window !== "undefined" &&
    window.localStorage.getItem(
      LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
    ) === "true";

  return !hideModal && chatSession.persona_id !== DEFAULT_PERSONA_ID;
};

export const showErrorNotification = (message: string) => {
  toast.error(message);
};

export interface MoveOperationParams {
  chatSession: ChatSession;
  targetProjectId: number;
  refreshChatSessions: () => Promise<any>;
  refreshCurrentProjectDetails: () => Promise<any>;
  fetchProjects: () => Promise<any>;
  currentProjectId: number | null;
}

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
