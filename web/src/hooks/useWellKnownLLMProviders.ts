"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

/**
 * Fetches the list of well-known (built-in) LLM providers and their models.
 *
 * Returns provider descriptors including known models and recommended defaults
 * for each supported provider (OpenAI, Anthropic, Vertex AI, Bedrock, etc.).
 *
 * @returns Object containing:
 *   - wellKnownLLMProviders: Array of provider descriptors, or null if not loaded
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - mutate: Function to manually revalidate the data
 */
export default function useWellKnownLLMProviders() {
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
