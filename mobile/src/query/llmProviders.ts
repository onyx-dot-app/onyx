// GET /llm/provider — the global provider list. v1 ignores the persona-scoped
// /llm/persona/{id}/providers variant.
import type { LLMProviderResponse } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

// Mirrors web useLLMProviders; returns the raw payload (callers read `.providers`).
export function useLlmProviders() {
  return useSimpleQuery<LLMProviderResponse>(queryKeys.llmProviders);
}
