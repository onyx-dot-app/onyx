import { buildLlmOptions, llmOptionKey } from "@/lib/languageModels/options";
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
  name: string,
  provider: string,
  modelConfigurations: ModelConfiguration[]
): LLMProviderDescriptor {
  return {
    id,
    name,
    provider,
    provider_display_name: name,
    model_configurations: modelConfigurations,
  };
}

describe("llmOptionKey", () => {
  it("gives distinct keys to same-named models from different providers", () => {
    const providers = [
      makeProvider(1, "OpenAI Main", "openai", [
        makeModelConfiguration(11, "gpt-4o"),
      ]),
      makeProvider(2, "OpenAI Backup", "openai", [
        makeModelConfiguration(22, "gpt-4o"),
      ]),
    ];

    const keys = buildLlmOptions(providers).map(llmOptionKey);

    expect(keys).toHaveLength(2);
    expect(new Set(keys).size).toBe(2);
  });

  it("keys by model configuration id when present", () => {
    expect(
      llmOptionKey({
        provider: "openai",
        modelName: "gpt-4o",
        modelConfigurationId: 11,
      })
    ).toBe("mc:11");
  });

  it("falls back to provider + model name without an id", () => {
    expect(
      llmOptionKey({
        provider: "openai",
        modelName: "gpt-4o",
        modelConfigurationId: null,
      })
    ).toBe("openai:gpt-4o");
    expect(llmOptionKey({ provider: "openai", modelName: "gpt-4o" })).toBe(
      "openai:gpt-4o"
    );
  });
});
