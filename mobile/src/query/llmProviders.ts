// LLM providers query. GET /llm/provider returns the list of configured providers
// (each with its visible model_configurations). Persona-scoped variant available at
// /llm/persona/{id}/providers; v1 uses the global list.
import type { LLMProviderResponse } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

// Returns the raw { providers, default_text, default_vision } payload. Callers read
// `.providers` (and `.default_text` for the default model). Mirrors web useLLMProviders.
export function useLlmProviders() {
  return useSimpleQuery<LLMProviderResponse>(queryKeys.llmProviders);
}
