import { LLMProviderDescriptor } from "@/interfaces/llm";
import { LLMOption } from "./interfaces";

/**
 * Build a flat list of LLM options from provider descriptors.
 * Pure utility — no React dependencies. Used by ModelSelector,
 * useMultiModelChat, ChatUI, and LLMPopover.
 */
export function buildLlmOptions(
  llmProviders: LLMProviderDescriptor[] | undefined,
  currentModelName?: string
): LLMOption[] {
  if (!llmProviders) {
    return [];
  }

  // Track seen combinations of provider + exact model name to avoid true duplicates
  // (same model appearing from multiple LLM provider configs with same provider type)
  const seenKeys = new Set<string>();
  const options: LLMOption[] = [];

  llmProviders.forEach((llmProvider) => {
    llmProvider.model_configurations
      .filter(
        (modelConfiguration) =>
          modelConfiguration.is_visible ||
          modelConfiguration.name === currentModelName
      )
      .forEach((modelConfiguration) => {
        // Deduplicate by exact provider + model name combination
        const key = `${llmProvider.provider}:${modelConfiguration.name}`;
        if (seenKeys.has(key)) {
          return;
        }
        seenKeys.add(key);

        options.push({
          name: llmProvider.name,
          provider: llmProvider.provider,
          providerDisplayName:
            llmProvider.provider_display_name || llmProvider.provider,
          modelName: modelConfiguration.name,
          displayName:
            modelConfiguration.display_name || modelConfiguration.name,
          vendor: modelConfiguration.vendor || null,
          maxInputTokens: modelConfiguration.max_input_tokens,
          region: modelConfiguration.region || null,
          version: modelConfiguration.version || null,
          supportsReasoning: modelConfiguration.supports_reasoning || false,
          supportsImageInput: modelConfiguration.supports_image_input || false,
        });
      });
  });

  return options;
}
