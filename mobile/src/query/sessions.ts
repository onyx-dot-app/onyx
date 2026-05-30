// Chat session queries + mutations.
//
// - useChatSessions: GET /api/chat/get-user-chat-sessions
// - useCreateSession / useRenameSession / useDeleteSession: mutations that invalidate
//   [queryKeys.chatSessions] on success. Rename + delete additionally do optimistic
//   updates (snapshot in onMutate, rollback in onError).
//
// Endpoint URLs + payloads are ported faithfully from web/src/app/app/services/lib.tsx.
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { errorHandlingFetcher } from "@/lib/api";
import type { ChatSessionSummary } from "@/lib/types";
import { queryKeys } from "./keys";
import { clientConfig } from "./client";

// The backend wraps the list in { sessions: [...], has_more }.
// (We use ChatSessionSummary per design doc 06; web's paginated hook types these as
// ChatSession, but the fields the mobile list touches — id, name — are shared.)
interface ChatSessionsResponse {
  sessions: ChatSessionSummary[];
  has_more?: boolean;
}

export function useChatSessions() {
  return useQuery({
    queryKey: [queryKeys.chatSessions],
    queryFn: () =>
      errorHandlingFetcher<ChatSessionsResponse>(
        queryKeys.chatSessions,
        clientConfig
      ),
    select: (data) => data.sessions,
  });
}

// ── Create ──────────────────────────────────────────────────────────────────────
interface CreateSessionArgs {
  personaId: number;
  description?: string | null;
  projectId?: number | null;
}

interface CreateSessionResponse {
  chat_session_id: string;
}

export function useCreateSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ personaId, description, projectId }: CreateSessionArgs) =>
      errorHandlingFetcher<CreateSessionResponse>(
        "/api/chat/create-chat-session",
        clientConfig,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            persona_id: personaId,
            description: description ?? null,
            project_id: projectId ?? null,
          }),
        }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [queryKeys.chatSessions] });
    },
  });
}

// ── Rename (optimistic) ───────────────────────────────────────────────────────
interface RenameSessionArgs {
  chatSessionId: string;
  newName: string;
}

interface RenameMutationContext {
  previous?: ChatSessionsResponse;
}

export function useRenameSession() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, RenameSessionArgs, RenameMutationContext>({
    mutationFn: ({ chatSessionId, newName }) =>
      errorHandlingFetcher("/api/chat/rename-chat-session", clientConfig, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_session_id: chatSessionId,
          name: newName,
        }),
      }),
    onMutate: async ({ chatSessionId, newName }) => {
      await queryClient.cancelQueries({ queryKey: [queryKeys.chatSessions] });
      const previous = queryClient.getQueryData<ChatSessionsResponse>([
        queryKeys.chatSessions,
      ]);
      if (previous) {
        queryClient.setQueryData<ChatSessionsResponse>(
          [queryKeys.chatSessions],
          {
            ...previous,
            sessions: previous.sessions.map((s) =>
              s.id === chatSessionId ? { ...s, name: newName } : s
            ),
          }
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          [queryKeys.chatSessions],
          context.previous
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: [queryKeys.chatSessions] });
    },
  });
}

// ── Delete (optimistic) ───────────────────────────────────────────────────────
interface DeleteMutationContext {
  previous?: ChatSessionsResponse;
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, string, DeleteMutationContext>({
    mutationFn: (chatSessionId: string) =>
      errorHandlingFetcher(
        `/api/chat/delete-chat-session/${chatSessionId}`,
        clientConfig,
        { method: "DELETE" }
      ),
    onMutate: async (chatSessionId) => {
      await queryClient.cancelQueries({ queryKey: [queryKeys.chatSessions] });
      const previous = queryClient.getQueryData<ChatSessionsResponse>([
        queryKeys.chatSessions,
      ]);
      if (previous) {
        queryClient.setQueryData<ChatSessionsResponse>(
          [queryKeys.chatSessions],
          {
            ...previous,
            sessions: previous.sessions.filter((s) => s.id !== chatSessionId),
          }
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          [queryKeys.chatSessions],
          context.previous
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: [queryKeys.chatSessions] });
    },
  });
}
