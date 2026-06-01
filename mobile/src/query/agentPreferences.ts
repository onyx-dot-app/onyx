// Per-agent tool enable/disable preferences (backend-persisted). The write path is
// per-persona and not in the endpoint registry, so it's built inline.
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
