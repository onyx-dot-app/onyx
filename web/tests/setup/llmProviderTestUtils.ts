import { LLMProviderDescriptor } from "@/interfaces/llm";

export function makeProvider(
  overrides: Partial<LLMProviderDescriptor>
): LLMProviderDescriptor {
  return {
    id: overrides.id ?? 1,
    name: overrides.name ?? "Provider",
    provider: overrides.provider ?? "openai",
    provider_display_name: overrides.provider_display_name ?? "Provider",
    model_configurations: overrides.model_configurations ?? [],
    ...overrides,
  };
}
