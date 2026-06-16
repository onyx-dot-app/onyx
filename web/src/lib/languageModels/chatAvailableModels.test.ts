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
    });
    expect(response.providers[0]!.model_configurations).toEqual([
      expect.objectContaining({
        id: 10,
        name: "gpt-5.5",
        display_name: "GPT-5.5",
        is_visible: true,
        supports_image_input: true,
        supports_reasoning: true,
      }),
      expect.objectContaining({
        id: 11,
        name: "qwen3.7-plus",
        display_name: "Qwen3.7 Plus",
        is_visible: true,
        supports_image_input: true,
        supports_reasoning: true,
      }),
    ]);
  });
});
