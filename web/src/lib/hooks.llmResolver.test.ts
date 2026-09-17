import {
  getDefaultLlmDescriptor,
  getValidLlmDescriptorForProviders,
} from "@/lib/hooks";
import { parseLlmDescriptor, structureValue } from "@/lib/languageModels/utils";
import { LLMProviderDescriptor } from "@/lib/languageModels/types";
import { makeProvider } from "@tests/setup/llmProviderTestUtils";

describe("LLM resolver helpers", () => {
  test("chooses provider-specific descriptor when model names collide", () => {
    const sharedModel = "shared-runtime-model";
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        id: 1,
        name: "OpenAI Provider",
        provider: "openai",
        model_configurations: [
          {
            name: sharedModel,
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
      makeProvider({
        id: 2,
        name: "Anthropic Provider",
        provider: "anthropic",
        model_configurations: [
          {
            name: sharedModel,
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
    ];

    const descriptor = getValidLlmDescriptorForProviders(
      structureValue("Anthropic Provider", "anthropic", sharedModel),
      providers
    );

    expect(descriptor).toEqual({
      name: "Anthropic Provider",
      provider: "anthropic",
      modelName: sharedModel,
    });
  });

  test("falls back to default provider when model is unavailable", () => {
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        id: 10,
        name: "Default OpenAI",
        provider: "openai",
        model_configurations: [
          {
            name: "gpt-4o-mini",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: true,
            supports_reasoning: false,
            effectiveDisplayName: "gpt-4o-mini",
          },
        ],
      }),
      makeProvider({
        id: 20,
        name: "Anthropic Backup",
        provider: "anthropic",
        model_configurations: [
          {
            name: "claude-3-5-sonnet",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: true,
            supports_reasoning: false,
            effectiveDisplayName: "claude-3-5-sonnet",
          },
        ],
      }),
    ];

    const descriptor = getValidLlmDescriptorForProviders(
      "unknown-model-name",
      providers
    );

    expect(descriptor).toEqual({
      name: "Default OpenAI",
      provider: "openai",
      modelName: "gpt-4o-mini",
    });
  });

  test("prefers provider by name when multiple share the same type", () => {
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        id: 1,
        name: "Anthropic",
        provider: "anthropic",
        model_configurations: [
          {
            name: "claude-sonnet-4-5",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
      makeProvider({
        id: 2,
        name: "PersonalAnthropicToken",
        provider: "anthropic",
        model_configurations: [
          {
            name: "claude-sonnet-4-5",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
    ];

    const descriptor = getValidLlmDescriptorForProviders(
      structureValue(
        "PersonalAnthropicToken",
        "anthropic",
        "claude-sonnet-4-5"
      ),
      providers
    );

    expect(descriptor).toEqual({
      name: "PersonalAnthropicToken",
      provider: "anthropic",
      modelName: "claude-sonnet-4-5",
    });
  });

  test("falls back to the global default when the saved model's provider is gone", () => {
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        id: 10,
        name: "First Provider",
        provider: "openai",
        model_configurations: [
          {
            name: "gpt-first",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
      makeProvider({
        id: 20,
        name: "Global Default Provider",
        provider: "anthropic",
        model_configurations: [
          {
            name: "claude-global-default",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
    ];

    // Personal default points at a provider that no longer exists (e.g. it
    // was deleted by an admin). The admin-configured global default should
    // win over the first provider in the list.
    const descriptor = getValidLlmDescriptorForProviders(
      structureValue("Deleted Provider", "litellm", "some-old-model"),
      providers,
      { provider_id: 20, model_name: "claude-global-default" }
    );

    expect(descriptor).toEqual({
      name: "Global Default Provider",
      provider: "anthropic",
      modelName: "claude-global-default",
    });
  });

  test("uses first provider with models when no explicit default exists", () => {
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        id: 30,
        name: "First Provider",
        provider: "openai",
        model_configurations: [
          {
            name: "gpt-first",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
      makeProvider({
        id: 40,
        name: "Second Provider",
        provider: "anthropic",
        model_configurations: [
          {
            name: "claude-second",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "",
          },
        ],
      }),
    ];

    expect(getDefaultLlmDescriptor(providers)).toEqual({
      name: "First Provider",
      provider: "openai",
      modelName: "gpt-first",
    });
  });
});

describe("duplicate provider display names", () => {
  const mc = (id: number, name: string, is_visible: boolean) => ({
    id,
    name,
    is_visible,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    effectiveDisplayName: "",
  });

  const sameNameProviders: LLMProviderDescriptor[] = [
    makeProvider({
      id: 22,
      name: "Gateway Dual",
      provider: "bifrost",
      model_configurations: [mc(101, "gateway/gpt-model", false)],
    }),
    makeProvider({
      id: 24,
      name: "Gateway Dual",
      provider: "bifrost",
      model_configurations: [mc(202, "gateway/gpt-model", true)],
    }),
  ];

  test("model configuration id resolves the exact row despite the shared name", () => {
    // The stored model segment is stale on purpose: only the id branch
    // re-derives the row's true model name, so this fails if the id path
    // regresses to name-based resolution.
    const descriptor = getValidLlmDescriptorForProviders(
      structureValue("Gateway Dual", "bifrost", "gateway/renamed-model", 202),
      sameNameProviders
    );

    expect(descriptor.modelConfigurationId).toBe(202);
    expect(descriptor.modelName).toBe("gateway/gpt-model");
  });

  test("structureValue round-trips the model configuration id", () => {
    const parsed = parseLlmDescriptor(
      structureValue("Gateway Dual", "bifrost", "gateway/gpt-model", 202)
    );
    expect(parsed.modelConfigurationId).toBe(202);
    expect(parsed.modelName).toBe("gateway/gpt-model");

    const legacy = parseLlmDescriptor(
      structureValue("Gateway Dual", "bifrost", "gateway/gpt-model")
    );
    expect(legacy.modelConfigurationId).toBeUndefined();
  });

  test("model names containing __ keep both the full name and the id", () => {
    const parsed = parseLlmDescriptor(
      structureValue("Gateway Dual", "bifrost", "org__model__v2", 7)
    );
    expect(parsed.modelName).toBe("org__model__v2");
    expect(parsed.modelConfigurationId).toBe(7);

    const legacy = parseLlmDescriptor(
      structureValue("Gateway Dual", "bifrost", "org__model__v2")
    );
    expect(legacy.modelName).toBe("org__model__v2");
    expect(legacy.modelConfigurationId).toBeUndefined();
  });

  test("legacy three-segment values still resolve by name", () => {
    const descriptor = getValidLlmDescriptorForProviders(
      structureValue("Gateway Dual", "bifrost", "gateway/gpt-model"),
      sameNameProviders
    );

    expect(descriptor.name).toBe("Gateway Dual");
    expect(descriptor.modelName).toBe("gateway/gpt-model");
  });
});
