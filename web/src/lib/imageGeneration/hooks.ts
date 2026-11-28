import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ImageGenerationConfigView,
  ImageGenerationLLMProvider,
  ImageGenerationProviderModel,
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

/**
 * The image models a provider can serve: a saved provider's, with the
 * connected ones marked, or the catalog's for a provider type that is not
 * saved yet. `undefined` while loading.
 */
export function useProviderImageModels(
  llmProviderId: number | undefined,
  providerType: string
): ImageGenerationProviderModel[] | undefined {
  const { providers } = useImageGenerationProviders();
  const { data: catalog } = useSWR<ImageGenerationProviderModel[]>(
    llmProviderId == null ? SWR_KEYS.imageGenCatalog(providerType) : null,
    errorHandlingFetcher
  );
  if (llmProviderId == null) return catalog;
  if (!providers) return undefined;
  return (
    providers.find((p) => p.llm_provider_id === llmProviderId)?.models ?? []
  );
}
