import { useCallback } from "react";

import { useCreateSession } from "@/query/sessions";
import { usePersonas } from "@/query/personas";
import { useChatSessionStore } from "@/state/chatSessionStore";

// Creates a fresh backend chat session (default persona) and makes it current.
// Returns the new chat_session_id. Used by the sidebar "New Chat" button and by the
// new-chat screen's mount guard. We pre-create the real session so useSendMessage is
// bound to a stable UUID from the start (no fragile mid-stream re-keying); empty
// sessions are filtered out of Recents by the backend's 5-min grace window.
export function useStartNewChat() {
  const { data: personas } = usePersonas();
  const createSession = useCreateSession();
  const setCurrentSession = useChatSessionStore((s) => s.setCurrentSession);

  return useCallback(async (): Promise<string | null> => {
    // Default to Onyx's built-in persona (id 0), else the first available.
    const personaId =
      personas?.find((p) => p.id === 0)?.id ?? personas?.[0]?.id ?? 0;
    try {
      const res = await createSession.mutateAsync({ personaId });
      setCurrentSession(res.chat_session_id);
      return res.chat_session_id;
    } catch {
      return null;
    }
  }, [personas, createSession, setCurrentSession]);
}
