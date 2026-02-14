import {
  getDefaultLlmDescriptor,
  getValidLlmDescriptorForProviders,
} from "@/lib/hooks";
import { structureValue } from "@/lib/llm/utils";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { makeProvider } from "@tests/setup/llmProviderTestUtils";

describe("LLM resolver helpers", () => {
  test("chooses provider-specific descriptor when model names collide", () => {
    const sharedModel = "shared-runtime-model";
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        name: "OpenAI Provider",
        provider: "openai",
        default_model_name: sharedModel,
        is_default_provider: true,
        model_configurations: [
          {
            name: sharedModel,
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
          },
        ],
      }),
      makeProvider({
        name: "Anthropic Provider",
        provider: "anthropic",
        default_model_name: sharedModel,
        model_configurations: [
          {
            name: sharedModel,
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
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
        name: "Default OpenAI",
        provider: "openai",
        default_model_name: "gpt-4o-mini",
        is_default_provider: true,
        model_configurations: [
          {
            name: "gpt-4o-mini",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: true,
          },
        ],
      }),
      makeProvider({
        name: "Anthropic Backup",
        provider: "anthropic",
        default_model_name: "claude-3-5-sonnet",
        model_configurations: [
          {
            name: "claude-3-5-sonnet",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: true,
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
        name: "First Provider",
        provider: "openai",
        default_model_name: "gpt-first",
        is_default_provider: false,
        model_configurations: [
          {
            name: "gpt-first",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
          },
        ],
      }),
      makeProvider({
        name: "Second Provider",
        provider: "anthropic",
        default_model_name: "claude-second",
        is_default_provider: false,
        model_configurations: [
          {
            name: "claude-second",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
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
