import { useCallback } from "react";

import { useStartNewChat } from "./useStartNewChat";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Enter a fresh chat draft bound to a project: resets to a draft and records the
// project so the first send creates the session with project_id (web parity). Order
// matters — useStartNewChat clears the target, so we set it AFTER.
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
