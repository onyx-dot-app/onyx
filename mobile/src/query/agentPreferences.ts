// Per-agent tool enable/disable preferences (backend-persisted, web parity).
//
//   - useAgentPreferences:      GET   /user/assistant/preferences
//                               -> UserSpecificAgentPreferences (Record<personaId, pref>)
//   - useUpdateAgentPreference: PATCH /user/assistant/{personaId}/preferences
//                               body { disabled_tool_ids: number[] } -> 204
//
// The read path lives in the endpoint registry (queryKeys.agentPreferences). The
// write path is per-persona and NOT in the registry, so it is built inline.
//
// The mutation mirrors query/sessions.ts:useRenameSession — optimistic onMutate,
// rollback onError, invalidate onSettled.
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { errorHandlingFetcher } from "@/lib/api";
import type {
  UserSpecificAgentPreference,
  UserSpecificAgentPreferences,
} from "@/lib/types/domain";

import { clientConfig, useSimpleQuery } from "./client";
import { queryKeys } from "./keys";

export function useAgentPreferences() {
  return useSimpleQuery<UserSpecificAgentPreferences>(
    queryKeys.agentPreferences,
    { staleTime: 60_000 }
  );
}

interface UpdateArgs {
  personaId: number;
  preference: UserSpecificAgentPreference;
}

interface UpdateMutationContext {
  previous?: UserSpecificAgentPreferences;
}

export function useUpdateAgentPreference() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, UpdateArgs, UpdateMutationContext>({
    mutationFn: ({ personaId, preference }) =>
      errorHandlingFetcher(
        `/user/assistant/${personaId}/preferences`,
        clientConfig,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(preference),
        }
      ),
    onMutate: async ({ personaId, preference }) => {
      await queryClient.cancelQueries({
        queryKey: [queryKeys.agentPreferences],
      });
      const previous = queryClient.getQueryData<UserSpecificAgentPreferences>([
        queryKeys.agentPreferences,
      ]);
      queryClient.setQueryData<UserSpecificAgentPreferences>(
        [queryKeys.agentPreferences],
        {
          ...(previous ?? {}),
          [personaId]: preference,
        }
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          [queryKeys.agentPreferences],
          context.previous
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: [queryKeys.agentPreferences],
      });
    },
  });
}
