import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ImageGenerationConfigView,
  ImageGenerationLLMProvider,
} from "@/lib/imageGeneration/types";

/** The connected image models, and which one is the default. */
export function useImageGenerationConfigs() {
  const { data, error, mutate } = useSWR<ImageGenerationConfigView[]>(
    SWR_KEYS.imageGenConfig,
    errorHandlingFetcher
  );
  return {
    configs: data,
    defaultConfig: data?.find((config) => config.is_default) ?? null,
    error,
    refetch: mutate,
  };
}

/** Each connected LLM provider with the image models it can serve. */
export function useImageGenerationProviders() {
  const { data, error, mutate } = useSWR<ImageGenerationLLMProvider[]>(
    SWR_KEYS.imageGenLlmProviders,
    errorHandlingFetcher
  );
  return { providers: data, error, refetch: mutate };
}
