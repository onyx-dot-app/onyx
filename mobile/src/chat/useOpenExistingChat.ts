import { useCallback } from "react";

import { useChatSessionStore } from "@/state/chatSessionStore";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Open an EXISTING chat session as the current one. Opening a recent/known chat is
// never a new project chat, so we first drop any lingering project target (it could
// otherwise bind a later draft to the wrong project) and then make the session
// current — which hydrates its history on demand.
//
// Callers own the surrounding navigation: the sidebar/project-folder rows close the
// drawer and navigate to the chat screen, while the project screen opens the thread
// in place (no nav). This hook only owns the clear + setCurrentSession core.
export function useOpenExistingChat() {
  const setCurrentSession = useChatSessionStore((s) => s.setCurrentSession);

  return useCallback(
    (chatSessionId: string) => {
      useProjectChatTarget.getState().clear();
      setCurrentSession(chatSessionId);
    },
    [setCurrentSession],
  );
}
