import { useCallback } from "react";

import { useChatSessionStore } from "@/state/chatSessionStore";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Open an existing chat session as current. Clears any lingering project target
// first (it could otherwise bind a later draft to the wrong project). Callers own
// navigation; this hook only owns the clear + setCurrentSession.
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
