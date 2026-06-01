// Chat-session lifecycle for the composer — mirrors web's lazy create + auto-name
// (see web useChatController): the session is created on first send, then auto-titled
// after the first response (rename with name=null).
import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { errorHandlingFetcher } from "@/lib/api";
import { clientConfig } from "@/query/client";
import { queryKeys } from "@/query/keys";
import { useCreateSession } from "@/query/sessions";
import { usePersonas } from "@/query/personas";
import { useProjectChatTarget } from "@/state/projectChatTarget";

export interface ChatSessionLifecycle {
  // Lazily create a backend session (default persona); null on failure.
  ensureSession: () => Promise<string | null>;
  autoNameSession: (chatSessionId: string) => Promise<void>;
}

export function useChatSessionLifecycle(): ChatSessionLifecycle {
  const { data: personas } = usePersonas();
  // mutateAsync is stable across renders, keeping ensureSession stable.
  const { mutateAsync: createSessionAsync } = useCreateSession();
  const queryClient = useQueryClient();

  const ensureSession = useCallback(async (): Promise<string | null> => {
    // Default to Onyx's built-in persona (id 0), else the first available.
    const personaId =
      personas?.find((p) => p.id === 0)?.id ?? personas?.[0]?.id ?? 0;
    // If launched from a project, bind the session to it (web parity: create-chat-session
    // carries project_id). Consumed once, then cleared so the next chat isn't stale.
    const projectId = useProjectChatTarget.getState().projectId;
    try {
      const res = await createSessionAsync({ personaId, projectId });
      if (projectId !== null) {
        useProjectChatTarget.getState().clear();
        // Refresh the project's chat list so the new session shows under it.
        queryClient.invalidateQueries({
          queryKey: [queryKeys.projectDetails(projectId)],
        });
        queryClient.invalidateQueries({ queryKey: [queryKeys.userProjects] });
      }
      return res.chat_session_id;
    } catch {
      return null;
    }
  }, [personas, createSessionAsync, queryClient]);

  const autoNameSession = useCallback(
    async (chatSessionId: string): Promise<void> => {
      // Backend write lags the stream-finish signal; web waits 200ms so the title
      // request sees a persisted session.
      await new Promise((resolve) => setTimeout(resolve, 200));
      try {
        // name:null tells the backend to auto-generate a title.
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
