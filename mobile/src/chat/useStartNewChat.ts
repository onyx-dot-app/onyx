import { useCallback } from "react";

import {
  DRAFT_SESSION_ID,
  useChatSessionStore,
} from "@/state/chatSessionStore";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Starts a fresh chat lazily (web parity): no backend session on tap, just resets
// to a draft (null). The real session is created on first send (useSendMessage →
// ensureSession), avoiding empty untitled sessions per "New Chat" tap.
export function useStartNewChat() {
  const setCurrentSession = useChatSessionStore((s) => s.setCurrentSession);
  const removeSession = useChatSessionStore((s) => s.removeSession);

  return useCallback(() => {
    // Plain "New Chat" is not inside a project — clear any leftover project target.
    useProjectChatTarget.getState().clear();
    // Drop leftover draft state (e.g. a model picked but never sent).
    removeSession(DRAFT_SESSION_ID);
    setCurrentSession(null);
  }, [removeSession, setCurrentSession]);
}
