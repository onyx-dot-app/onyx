import { buildLlmOptions, groupLlmOptions, LLMOption } from "./llmPopoverUtils";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

function makeProvider(
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

describe("LLMPopover helpers", () => {
  test("deduplicates identical provider+model combinations across provider entries", () => {
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        name: "OpenAI A",
        provider: "openai",
        model_configurations: [
          {
            name: "shared-model",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
          },
        ],
      }),
      makeProvider({
        name: "OpenAI B",
        provider: "openai",
        model_configurations: [
          {
            name: "shared-model",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
          },
        ],
      }),
      makeProvider({
        name: "Anthropic A",
        provider: "anthropic",
        model_configurations: [
          {
            name: "shared-model",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
          },
        ],
      }),
    ];

    const options = buildLlmOptions(providers);
    const sharedModelOptions = options.filter(
      (o) => o.modelName === "shared-model"
    );

    expect(sharedModelOptions).toHaveLength(2);
    expect(sharedModelOptions.map((o) => o.provider).sort()).toEqual([
      "anthropic",
      "openai",
    ]);
  });

  test("includes currently selected hidden model in options", () => {
    const providers: LLMProviderDescriptor[] = [
      makeProvider({
        name: "OpenAI A",
        provider: "openai",
        model_configurations: [
          {
            name: "hidden-selected-model",
            is_visible: false,
            max_input_tokens: null,
            supports_image_input: false,
          },
        ],
      }),
    ];

    const options = buildLlmOptions(providers, "hidden-selected-model");
    expect(options.map((o) => o.modelName)).toContain("hidden-selected-model");
  });

  test("groups aggregator options by provider/vendor and sorts by display name", () => {
    const options: LLMOption[] = [
      {
        name: "Bedrock Provider",
        provider: "bedrock",
        providerDisplayName: "Amazon Bedrock",
        modelName: "claude-3-5-sonnet",
        displayName: "Claude 3.5 Sonnet",
        vendor: "anthropic",
      },
      {
        name: "OpenAI Provider",
        provider: "openai",
        providerDisplayName: "ChatGPT (OpenAI)",
        modelName: "gpt-4o-mini",
        displayName: "GPT-4o Mini",
        vendor: null,
      },
    ];

    const grouped = groupLlmOptions(options);

    expect(grouped.map((group) => group.key)).toEqual([
      "bedrock/anthropic",
      "openai",
    ]);
    expect(grouped[0]?.displayName).toBe("Amazon Bedrock/Anthropic");
    expect(grouped[1]?.displayName).toBe("ChatGPT (OpenAI)");
    expect(grouped[0]?.options).toHaveLength(1);
    expect(grouped[1]?.options).toHaveLength(1);
  });
});
