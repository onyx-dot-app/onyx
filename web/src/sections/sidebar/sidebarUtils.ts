import { ChatSession } from "@/app/chat/interfaces";
import { LOCAL_STORAGE_KEYS, DEFAULT_PERSONA_ID } from "./constants";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";

export const shouldShowMoveModal = (chatSession: ChatSession): boolean => {
  const hideModal =
    typeof window !== "undefined" &&
    window.localStorage.getItem(
      LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
    ) === "true";

  return !hideModal && chatSession.persona_id !== DEFAULT_PERSONA_ID;
};

type PopupType = "success" | "error" | "info" | "warning";

type SetPopupFn = (popup: { type: PopupType; message: string }) => void;

export const showErrorNotification = (
  setPopup: SetPopupFn,
  message: string
) => {
  setPopup({ type: "error", message });
};

export interface MoveOperationParams {
  chatSession: ChatSession;
  targetProjectId: number;
  refreshChatSessions: () => Promise<any>;
  refreshCurrentProjectDetails: () => Promise<any>;
  fetchProjects: () => Promise<any>;
  currentProjectId: number | null;
}

export const handleMoveOperation = async (
  {
    chatSession,
    targetProjectId,
    refreshChatSessions,
    refreshCurrentProjectDetails,
    fetchProjects,
    currentProjectId,
  }: MoveOperationParams,
  setPopup: SetPopupFn
) => {
  try {
    const projectRefreshPromise = currentProjectId
      ? refreshCurrentProjectDetails()
      : fetchProjects();
    await Promise.all([refreshChatSessions(), projectRefreshPromise]);
  } catch (error) {
    console.error("Failed to perform move operation:", error);
    showErrorNotification(setPopup, "Failed to move chat. Please try again.");
    throw error;
  }
};
