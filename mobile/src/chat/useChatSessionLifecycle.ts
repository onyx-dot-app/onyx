// Chat-session lifecycle for the composer — mirrors web's lazy create + auto-name.
//
// Web parity (see web useChatController):
//   • A new chat creates NO backend session on the "New Chat" tap. The session is
//     created only when the first message is sent (ensureSession), so the URL/state
//     can carry a real UUID before streaming.
//   • After the first response, the frontend asks the backend to auto-title the
//     session (rename with name=null → backend generates the title from the chat).
//
// useSendMessage composes this so the streaming hook owns the full first-message flow.
import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { errorHandlingFetcher } from "@/lib/api";
import { clientConfig } from "@/query/client";
import { queryKeys } from "@/query/keys";
import { useCreateSession } from "@/query/sessions";
import { usePersonas } from "@/query/personas";

export interface ChatSessionLifecycle {
  /** Lazily create a backend chat session (default persona). Returns its id, or null on failure. */
  ensureSession: () => Promise<string | null>;
  /** Ask the backend to auto-title a session from its first exchange (web parity). */
  autoNameSession: (chatSessionId: string) => Promise<void>;
}

export function useChatSessionLifecycle(): ChatSessionLifecycle {
  const { data: personas } = usePersonas();
  // mutateAsync is a stable reference across renders (react-query), so depending on
  // it keeps ensureSession stable instead of churning every render.
  const { mutateAsync: createSessionAsync } = useCreateSession();
  const queryClient = useQueryClient();

  const ensureSession = useCallback(async (): Promise<string | null> => {
    // Default to Onyx's built-in persona (id 0), else the first available.
    const personaId =
      personas?.find((p) => p.id === 0)?.id ?? personas?.[0]?.id ?? 0;
    try {
      const res = await createSessionAsync({ personaId });
      return res.chat_session_id;
    } catch {
      return null;
    }
  }, [personas, createSessionAsync]);

  const autoNameSession = useCallback(
    async (chatSessionId: string): Promise<void> => {
      // The backend write can lag the stream-finish signal slightly; web waits 200ms
      // before naming. Mirror that so the title request sees a persisted session.
      await new Promise((resolve) => setTimeout(resolve, 200));
      try {
        // name:null tells the backend to auto-generate a title from the conversation.
        await errorHandlingFetcher("/chat/rename-chat-session", clientConfig, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_session_id: chatSessionId, name: null }),
        });
      } catch {
        // Non-fatal: the session simply shows as "New Chat" until a later refresh.
      } finally {
        // Refresh Recents so the freshly-named session appears with its title.
        queryClient.invalidateQueries({ queryKey: [queryKeys.chatSessions] });
      }
    },
    [queryClient],
  );

  return { ensureSession, autoNameSession };
}
