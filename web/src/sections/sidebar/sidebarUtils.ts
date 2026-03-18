import { ChatSession } from "@/app/app/interfaces";
import {
  DEFAULT_PERSONA_ID,
  LEGACY_LOCAL_STORAGE_KEYS,
  LOCAL_STORAGE_KEYS,
} from "./constants";
import { moveChatSession } from "@/app/app/projects/projectsService";
import { toast } from "@/hooks/useToast";

export function shouldHideMoveCustomAgentModal(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  const hideModal = window.localStorage.getItem(
    LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
  );
  if (hideModal !== null) {
    return hideModal === "true";
  }

  const legacyHideModal = window.localStorage.getItem(
    LEGACY_LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
  );
  if (legacyHideModal !== null) {
    window.localStorage.setItem(
      LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
      legacyHideModal
    );
    window.localStorage.removeItem(
      LEGACY_LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
    );
    return legacyHideModal === "true";
  }

  return false;
}

export function persistHideMoveCustomAgentModal(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
    "true"
  );
  window.localStorage.removeItem(
    LEGACY_LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
  );
}

export const shouldShowMoveModal = (chatSession: ChatSession): boolean =>
  !shouldHideMoveCustomAgentModal() &&
  chatSession.persona_id !== DEFAULT_PERSONA_ID;

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
