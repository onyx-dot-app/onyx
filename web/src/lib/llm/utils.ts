import { Persona } from "@/app/admin/assistants/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/models/llm/interfaces";

export function getFinalLLM(
  llmProviders: LLMProviderDescriptor[],
  persona: Persona | null
): [string, string] {
  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );

  let provider = defaultProvider?.provider || "";
  let model = defaultProvider?.default_model_name || "";

  if (persona) {
    provider = persona.llm_model_provider_override || provider;
    model = persona.llm_model_version_override || model;
  }

  return [provider, model];
}

const MODELS_SUPPORTING_IMAGES = [
  ["openai", "gpt-4o"],
  ["openai", "gpt-4-vision-preview"],
  ["openai", "gpt-4-turbo"],
  ["openai", "gpt-4-1106-vision-preview"],
];

export function checkLLMSupportsImageInput(provider: string, model: string) {
  return MODELS_SUPPORTING_IMAGES.some(
    ([p, m]) => p === provider && m === model
  );
}
