// LLM providers query. GET /llm/provider returns the list of configured providers
// (each with its visible model_configurations). Persona-scoped variant available at
// /llm/persona/{id}/providers; v1 uses the global list.
import { useQuery } from "@tanstack/react-query";
import { errorHandlingFetcher } from "@/lib/api";
import type { LLMProviderResponse } from "@/lib/types";
import { queryKeys } from "./keys";
import { clientConfig } from "./client";

// Returns the raw { providers, default_text, default_vision } payload. Callers read
// `.providers` (and `.default_text` for the default model). Mirrors web useLLMProviders.
export function useLlmProviders() {
  return useQuery({
    queryKey: [queryKeys.llmProviders],
    queryFn: () =>
      errorHandlingFetcher<LLMProviderResponse>(
        queryKeys.llmProviders,
        clientConfig,
      ),
  });
}
