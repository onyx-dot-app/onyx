import { availableChatModelsToProviderResponse } from "@/lib/languageModels/chatAvailableModels";

describe("availableChatModelsToProviderResponse", () => {
  it("groups backend chat models by provider and preserves capabilities", () => {
    const response = availableChatModelsToProviderResponse({
      models: [
        {
          provider_id: 1,
          provider_name: "Glomi Default",
          provider_type: "openai_compatible",
          provider_display_name: "Glomi",
          supplier_id: "gpt",
          supplier_display_name: "GPT",
          model_configuration_id: 10,
          model_id: "gpt-5.5",
          display_name: "GPT-5.5",
          supports_image_input: true,
          supports_reasoning: true,
          roles: ["balanced", "vision"],
          is_default: true,
          is_selected: false,
        },
        {
          provider_id: 1,
          provider_name: "Glomi Default",
          provider_type: "openai_compatible",
          provider_display_name: "Glomi",
          supplier_id: "gpt",
          supplier_display_name: "GPT",
          model_configuration_id: 11,
          model_id: "qwen3.7-plus",
          display_name: "Qwen3.7 Plus",
          supports_image_input: true,
          supports_reasoning: true,
          roles: ["balanced", "vision"],
          is_default: false,
          is_selected: true,
        },
      ],
    });

    expect(response.default_text).toEqual({
      provider_id: 1,
      model_name: "gpt-5.5",
    });
    expect(response.providers).toHaveLength(1);
    expect(response.providers[0]).toMatchObject({
      id: 1,
      name: "Glomi Default",
      provider: "openai_compatible",
      provider_display_name: "Glomi",
      supplier_id: "gpt",
      supplier_display_name: "GPT",
    });
    expect(response.providers[0]!.model_configurations).toEqual([
      expect.objectContaining({
        id: 10,
        name: "gpt-5.5",
        display_name: "GPT-5.5",
        supplier_id: "gpt",
        supplier_display_name: "GPT",
        is_visible: true,
        supports_image_input: true,
        supports_reasoning: true,
      }),
      expect.objectContaining({
        id: 11,
        name: "qwen3.7-plus",
        display_name: "Qwen3.7 Plus",
        supplier_id: "gpt",
        supplier_display_name: "GPT",
        is_visible: true,
        supports_image_input: true,
        supports_reasoning: true,
      }),
    ]);
  });

  it("keeps GPT and MiniMax as separate backend provider groups", () => {
    const response = availableChatModelsToProviderResponse({
      models: [
        {
          provider_id: 1,
          provider_name: "Glomi Default",
          provider_type: "openai_compatible",
          provider_display_name: "OpenAI-Compatible",
          supplier_id: "gpt",
          supplier_display_name: "GPT",
          model_configuration_id: 10,
          model_id: "gpt-5.5",
          display_name: "GPT-5.5",
          supports_image_input: true,
          supports_reasoning: true,
          roles: ["balanced", "vision"],
          is_default: true,
          is_selected: false,
        },
        {
          provider_id: 2,
          provider_name: "Glomi MiniMax",
          provider_type: "openai_compatible",
          provider_display_name: "OpenAI-Compatible",
          supplier_id: "minimax",
          supplier_display_name: "MiniMax",
          model_configuration_id: 20,
          model_id: "MiniMax-M3",
          display_name: "MiniMax-M3",
          supports_image_input: true,
          supports_reasoning: true,
          roles: ["balanced", "vision"],
          is_default: false,
          is_selected: true,
        },
      ],
    });

    expect(response.providers).toHaveLength(2);
    expect(response.providers.map((provider) => provider.supplier_id)).toEqual([
      "gpt",
      "minimax",
    ]);
  });
});
