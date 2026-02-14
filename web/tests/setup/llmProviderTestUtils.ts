import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

export function makeProvider(
  overrides: Partial<LLMProviderDescriptor>
): LLMProviderDescriptor {
  return {
    name: overrides.name ?? "Provider",
    provider: overrides.provider ?? "openai",
    default_model_name: overrides.default_model_name ?? "default-model",
    is_default_provider: overrides.is_default_provider ?? false,
    model_configurations: overrides.model_configurations ?? [],
    ...overrides,
  };
}
