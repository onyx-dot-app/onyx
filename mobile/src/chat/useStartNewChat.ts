import { useCallback } from "react";

import {
  DRAFT_SESSION_ID,
  useChatSessionStore,
} from "@/state/chatSessionStore";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Starts a fresh chat — LAZILY, matching web. Clicking "New Chat" creates NO
// backend session; it just resets the current session to a draft (null). The real
// backend session is created on the first message send (see useSendMessage →
// useChatSessionLifecycle.ensureSession), which also triggers backend auto-naming.
// This avoids spawning empty, untitled sessions on every "New Chat" tap.
export function useStartNewChat() {
  const setCurrentSession = useChatSessionStore((s) => s.setCurrentSession);
  const removeSession = useChatSessionStore((s) => s.removeSession);

  return useCallback(() => {
    // A plain "New Chat" is NOT inside a project — clear any project target left
    // over from a project-screen launcher that was never sent.
    useProjectChatTarget.getState().clear();
    // Drop leftover draft state (e.g. a model picked but never sent) so the new
    // chat starts clean, then reset to a draft.
    removeSession(DRAFT_SESSION_ID);
    setCurrentSession(null);
  }, [removeSession, setCurrentSession]);
}
