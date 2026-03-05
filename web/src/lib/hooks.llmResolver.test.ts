import {
  getDefaultLlmDescriptor,
  getValidLlmDescriptorForProviders,
} from "@/lib/hooks";
import { structureValue } from "@/lib/llmConfig/utils";
import { LLMProviderDescriptor } from "@/interfaces/llm";
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
