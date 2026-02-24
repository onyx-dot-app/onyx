"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  LLMProviderDescriptor,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";

/**
 * Fetches configured LLM providers accessible to the current user.
 *
 * @param personaId - Optional persona ID for RBAC-scoped providers.
 *   - `undefined`: public providers only (`/api/llm/provider`)
 *   - `number`: persona-specific providers with RBAC enforcement
 */
export function useLLMProviders(personaId?: number) {
  const url =
    typeof personaId === "number"
      ? `/api/llm/persona/${personaId}/providers`
      : "/api/llm/provider";

  const { data, error, mutate } = useSWR<LLMProviderDescriptor[] | undefined>(
    url,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false, // Cache aggressively for performance
      dedupingInterval: 60000, // Dedupe requests within 1 minute
    }
  );

  return {
    llmProviders: data,
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}

/**
 * Fetches the list of well-known (built-in) LLM providers and their models.
 *
 * Returns provider descriptors including known models and recommended defaults
 * for each supported provider (OpenAI, Anthropic, Vertex AI, Bedrock, etc.).
 */
export function useWellKnownLLMProviders() {
  const {
    data: wellKnownLLMProviders,
    error,
    isLoading,
    mutate,
  } = useSWR<WellKnownLLMProviderDescriptor[]>(
    "/api/admin/llm/built-in/options",
    errorHandlingFetcher
  );

  return {
    wellKnownLLMProviders: wellKnownLLMProviders ?? null,
    isLoading,
    error,
    mutate,
  };
}
