import {
  buildLlmOptions,
  groupLlmOptions,
  llmOptionKey,
} from "@/lib/languageModels/options";
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

describe("buildLlmOptions", () => {
  it("includes hidden models when requested by an admin picker", () => {
    const hiddenModel = {
      ...makeModelConfiguration(11, "hidden-model"),
      is_visible: false,
    };
    const providers = [makeProvider(1, "OpenAI", "openai", [hiddenModel])];

    expect(buildLlmOptions(providers)).toHaveLength(0);
    expect(buildLlmOptions(providers, undefined, true)).toEqual([
      expect.objectContaining({ modelName: "hidden-model" }),
    ]);
  });
});

describe("groupLlmOptions", () => {
  // Venice is a gateway: one connection serves Anthropic, Google, OpenAI and
  // open-weight models. Sub-grouping only happens for providers listed in
  // AGGREGATOR_PROVIDERS, and that list is duplicated between `./svc` (which
  // this path reads) and `./index` (which the icon resolver reads). Venice
  // missing from either half leaves one flat group of every hosted model.
  it("splits Venice's models by vendor", () => {
    const provider = makeProvider(1, "Venice", "venice", [
      { ...makeModelConfiguration(11, "claude-opus-4-5"), vendor: "Anthropic" },
      { ...makeModelConfiguration(12, "gemini-3-6-flash"), vendor: "Google" },
    ]);

    const groups = groupLlmOptions(buildLlmOptions([provider]));

    expect(groups.map((group) => group.displayName)).toEqual([
      "Venice/Anthropic",
      "Venice/Google",
    ]);
  });
});
