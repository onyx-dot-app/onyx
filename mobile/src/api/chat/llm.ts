import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import {
  buildModelOptions,
  resolveDefaultOption,
  type LlmProvidersResponse,
  type ModelOption,
} from "@/chat/models";
import { useSession } from "@/state/session";

const NO_OPTIONS: ModelOption[] = [];

/*
 * Scoped to one agent because each exposes its own subset of models. Asking per agent is cheap:
 * the backend caches this listing.
 */
export function useLlmProviders(
  agentId: number | null,
  currentModelName?: string,
) {
  const serverUrl = useSession((state) => state.serverUrl);
  const query = useQuery({
    queryKey: QUERY_KEYS.llmProviders(serverUrl, agentId),
    // Stays idle until a server is connected, because `getBaseUrl()` throws without one.
    enabled: serverUrl !== null && agentId !== null,
    queryFn: ({ signal }) =>
      apiFetch<LlmProvidersResponse>(`/llm/persona/${agentId}/providers`, {
        signal,
      }),
  });

  const providers = query.data?.providers;

  const options = useMemo(
    () =>
      providers ? buildModelOptions(providers, currentModelName) : NO_OPTIONS,
    [providers, currentModelName],
  );

  const defaultOption = useMemo(
    () =>
      providers
        ? resolveDefaultOption(
            providers,
            query.data?.default_text ?? null,
            options,
          )
        : null,
    [providers, query.data?.default_text, options],
  );

  return { ...query, options, defaultOption };
}
