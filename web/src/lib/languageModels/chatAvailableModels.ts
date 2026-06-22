import {
  AvailableChatModelsResponse,
  DefaultModel,
  LLMProviderDescriptor,
  LLMProviderResponse,
} from "@/lib/languageModels/types";

export function availableChatModelsToProviderResponse(
  availableModels: AvailableChatModelsResponse
): LLMProviderResponse<LLMProviderDescriptor> {
  const providersById = new Map<number, LLMProviderDescriptor>();
  let defaultText: DefaultModel | null = null;
  let defaultVision: DefaultModel | null = null;

  for (const model of availableModels.models) {
    if (!providersById.has(model.provider_id)) {
      providersById.set(model.provider_id, {
        id: model.provider_id,
        name: model.provider_name,
        provider: model.provider_type,
        provider_display_name: model.provider_display_name,
        supplier_id: model.supplier_id,
        supplier_display_name: model.supplier_display_name,
        model_configurations: [],
      });
    }

    const provider = providersById.get(model.provider_id)!;
    provider.model_configurations.push({
      id: model.model_configuration_id ?? undefined,
      name: model.model_id,
      is_visible: true,
      max_input_tokens: null,
      supports_image_input: model.supports_image_input,
      supports_reasoning: model.supports_reasoning,
      is_recommended_default: model.is_default,
      display_name: model.display_name,
      custom_display_name: undefined,
      provider_display_name: model.provider_display_name,
      supplier_id: model.supplier_id ?? undefined,
      supplier_display_name: model.supplier_display_name ?? undefined,
      vendor: undefined,
      version: undefined,
      region: undefined,
      roles: model.roles,
    });

    if (model.is_default) {
      defaultText = {
        provider_id: model.provider_id,
        model_name: model.model_id,
      };
      if (model.supports_image_input) {
        defaultVision = {
          provider_id: model.provider_id,
          model_name: model.model_id,
        };
      }
    }
  }

  return {
    providers: Array.from(providersById.values()),
    default_text: defaultText,
    default_vision: defaultVision,
  };
}
