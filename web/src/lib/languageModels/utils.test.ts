import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import type {
  LLMProviderDescriptor,
  ModelConfiguration,
} from "@/lib/languageModels/types";

function makeModelConfiguration(id: number, name: string): ModelConfiguration {
  return {
    id,
    name,
    is_visible: true,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    effectiveDisplayName: name,
  };
}

function makeProvider(
  id: number,
  name: string | null,
  provider: string,
  modelConfigurations: ModelConfiguration[]
): LLMProviderDescriptor {
  return {
    id,
    name,
    provider,
    provider_display_name: name ?? provider,
    model_configurations: modelConfigurations,
  };
}

describe("findProviderOwningModelConfig", () => {
  it("picks the owning provider when two providers share a display name", () => {
    // `llm_provider.name` has no unique constraint. A name lookup returns the
    // first match, which here does not own the model.
    const providers = [
      makeProvider(43, "Daily", "azure", [
        makeModelConfiguration(295, "mistral-large-3"),
      ]),
      makeProvider(54, "Daily", "azure", [
        makeModelConfiguration(306, "gpt-5.6-luna"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, 306)?.id).toBe(54);
    expect(findProviderOwningModelConfig(providers, 295)?.id).toBe(43);
  });

  it("distinguishes same-named providers of different types", () => {
    const providers = [
      makeProvider(48, "Advanced", "azure", [
        makeModelConfiguration(300, "gpt-5.6-terra"),
      ]),
      makeProvider(49, "Advanced", "azure_ai", [
        makeModelConfiguration(301, "claude-sonnet-5"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, 301)?.id).toBe(49);
  });

  it("distinguishes nameless providers of the same type", () => {
    // Well-known providers are frequently saved with a null name, so matching on
    // provider type plus a null name matched every one of them.
    const providers = [
      makeProvider(1, null, "openai", [makeModelConfiguration(11, "gpt-4o")]),
      makeProvider(2, null, "openai", [makeModelConfiguration(22, "gpt-4o")]),
    ];

    expect(findProviderOwningModelConfig(providers, 22)?.id).toBe(2);
  });

  it("returns undefined when no provider owns the model configuration", () => {
    const providers = [
      makeProvider(1, "OpenAI", "openai", [
        makeModelConfiguration(11, "gpt-4o"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, 999)).toBeUndefined();
  });

  it("returns undefined for a missing model configuration id", () => {
    const providers = [
      makeProvider(1, "OpenAI", "openai", [
        makeModelConfiguration(11, "gpt-4o"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, null)).toBeUndefined();
    expect(findProviderOwningModelConfig(providers, undefined)).toBeUndefined();
    expect(findProviderOwningModelConfig(undefined, 11)).toBeUndefined();
  });
});

describe("findProviderOwningModelConfig with nameless providers", () => {
  it("still resolves when the owning provider has no display name", () => {
    // Well-known providers are frequently saved with a null name, so any
    // resolution path that requires one drops a valid configured default.
    const providers = [
      makeProvider(1, "Named", "openai", [
        makeModelConfiguration(11, "gpt-4o"),
      ]),
      makeProvider(2, null, "openai", [makeModelConfiguration(22, "gpt-4o")]),
    ];

    expect(findProviderOwningModelConfig(providers, 22)?.id).toBe(2);
    expect(findProviderOwningModelConfig(providers, 22)?.name).toBeNull();
  });
});
