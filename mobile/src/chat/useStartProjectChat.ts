import { useCallback } from "react";

import { useStartNewChat } from "./useStartNewChat";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Enter a fresh chat draft BOUND to a project. Used at the project entry points
// (sidebar tap, create-project, the project screen's "new chat" button): it
// resets to a draft (currentSessionId → null, which makes the project screen show
// its landing) and records the project so the first send creates the backend
// session with project_id (web parity). Order matters — useStartNewChat clears the
// target, so we set it AFTER.
export function useStartProjectChat() {
  const startNewChat = useStartNewChat();
  return useCallback(
    (projectId: number) => {
      startNewChat();
      useProjectChatTarget.getState().setProjectId(projectId);
    },
    [startNewChat],
  );
}
