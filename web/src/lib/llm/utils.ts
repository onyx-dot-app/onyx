import { Persona } from "@/app/admin/assistants/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { LlmOverride } from "@/lib/hooks";

export function getFinalLLM(
  llmProviders: LLMProviderDescriptor[],
  persona: Persona | null,
  llmOverride: LlmOverride | null
): [string, string] {
  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );

  let provider = defaultProvider?.provider || "";
  let model = defaultProvider?.default_model_name || "";

  if (persona) {
    // Map "provider override" to actual LLLMProvider
    if (persona.llm_model_provider_override) {
      const underlyingProvider = llmProviders.find(
        (item: LLMProviderDescriptor) =>
          item.name === persona.llm_model_provider_override
      );
      provider = underlyingProvider?.provider || provider;
    }
    model = persona.llm_model_version_override || model;
  }

  if (llmOverride) {
    provider = llmOverride.provider || provider;
    model = llmOverride.modelName || model;
  }

  return [provider, model];
}

export function getLLMProviderOverrideForPersona(
  liveAssistant: Persona,
  llmProviders: LLMProviderDescriptor[]
): LlmOverride | null {
  const overrideProvider = liveAssistant.llm_model_provider_override;
  const overrideModel = liveAssistant.llm_model_version_override;

  if (!overrideModel) {
    return null;
  }

  const matchingProvider = llmProviders.find(
    (provider) =>
      (overrideProvider ? provider.name === overrideProvider : true) &&
      provider.model_names.includes(overrideModel)
  );

  if (matchingProvider) {
    return {
      name: matchingProvider.name,
      provider: matchingProvider.provider,
      modelName: overrideModel,
    };
  }

  return null;
}

const MODEL_NAMES_SUPPORTING_IMAGE_INPUT = [
  "gpt-4o",
  "gpt-4o-mini",
  "gpt-4-vision-preview",
  "gpt-4-turbo",
  "gpt-4-1106-vision-preview",
  // standard claude names
  "claude-3-5-sonnet-20240620",
  "claude-3-5-sonnet-20241022",
  "claude-3-opus-20240229",
  "claude-3-sonnet-20240229",
  "claude-3-haiku-20240307",
  // claude names with AWS Bedrock Suffix
  "claude-3-opus-20240229-v1:0",
  "claude-3-sonnet-20240229-v1:0",
  "claude-3-haiku-20240307-v1:0",
  "claude-3-5-sonnet-20240620-v1:0",
  "claude-3-5-sonnet-20241022-v2:0",
  // claude names with full AWS Bedrock names
  "anthropic.claude-3-opus-20240229-v1:0",
  "anthropic.claude-3-sonnet-20240229-v1:0",
  "anthropic.claude-3-haiku-20240307-v1:0",
  "anthropic.claude-3-5-sonnet-20240620-v1:0",
  "anthropic.claude-3-5-sonnet-20241022-v2:0",
  // google gemini model names
  "gemini-1.5-pro",
  "gemini-1.5-flash",
  "gemini-1.5-pro-001",
  "gemini-1.5-flash-001",
  "gemini-1.5-pro-002",
  "gemini-1.5-flash-002",
];

export function checkLLMSupportsImageInput(model: string) {
  // Original exact match check
  const exactMatch = MODEL_NAMES_SUPPORTING_IMAGE_INPUT.some(
    (modelName) => modelName === model
  );

  if (exactMatch) {
    return true;
  }

  // Additional check for the last part of the model name
  const modelParts = model.split(/[/.]/);
  const lastPart = modelParts[modelParts.length - 1];

  return MODEL_NAMES_SUPPORTING_IMAGE_INPUT.some((modelName) => {
    const modelNameParts = modelName.split(/[/.]/);
    const modelNameLastPart = modelNameParts[modelNameParts.length - 1];
    return modelNameLastPart === lastPart;
  });
}

export const structureValue = (
  name: string,
  provider: string,
  modelName: string
) => {
  return `${name}__${provider}__${modelName}`;
};

export const destructureValue = (value: string): LlmOverride => {
  const [displayName, provider, modelName] = value.split("__");
  return {
    name: displayName,
    provider,
    modelName,
  };
};
