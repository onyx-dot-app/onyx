import {
  findProviderOwningModelConfig,
  getModelIcon,
} from "@/lib/languageModels/utils";
import { LLMProviderName } from "@/lib/languageModels/types";
import { SvgClaude, SvgGemini, SvgVenice } from "@opal/logos";
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
        makeModelConfiguration(306, "gpt-6-luna"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, 306)?.id).toBe(54);
    expect(findProviderOwningModelConfig(providers, 295)?.id).toBe(43);
  });

  it("distinguishes same-named providers of different types", () => {
    const providers = [
      makeProvider(48, "Advanced", "azure", [
        makeModelConfiguration(300, "gpt-6.1-sol"),
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
      makeProvider(1, null, "openai", [
        makeModelConfiguration(11, "gpt-6-sol"),
      ]),
      makeProvider(2, null, "openai", [
        makeModelConfiguration(22, "gpt-6-sol"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, 22)?.id).toBe(2);
  });

  it("returns undefined when no provider owns the model configuration", () => {
    const providers = [
      makeProvider(1, "OpenAI", "openai", [
        makeModelConfiguration(11, "gpt-6-sol"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, 999)).toBeUndefined();
  });

  it("returns undefined for a missing model configuration id", () => {
    const providers = [
      makeProvider(1, "OpenAI", "openai", [
        makeModelConfiguration(11, "gpt-6-sol"),
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
        makeModelConfiguration(11, "gpt-6-sol"),
      ]),
      makeProvider(2, null, "openai", [
        makeModelConfiguration(22, "gpt-6-sol"),
      ]),
    ];

    expect(findProviderOwningModelConfig(providers, 22)?.id).toBe(2);
    expect(findProviderOwningModelConfig(providers, 22)?.name).toBeNull();
  });
});

describe("getModelIcon", () => {
  // Venice serves Anthropic, Google and open-source models alongside its own,
  // so the vendor has to win over the provider. Without Venice in
  // AGGREGATOR_PROVIDERS the provider-name branch matches first and every
  // model in the picker wears the Venice keys.
  it("prefers the vendor mark for models Venice hosts", () => {
    expect(getModelIcon(LLMProviderName.VENICE, "claude-opus-4-5")).toBe(
      SvgClaude
    );
    expect(getModelIcon(LLMProviderName.VENICE, "gemini-3-6-flash")).toBe(
      SvgGemini
    );
  });

  it("falls back to the Venice mark for Venice's own models", () => {
    expect(getModelIcon(LLMProviderName.VENICE, "venice-uncensored-1-2")).toBe(
      SvgVenice
    );
  });
});
