/**
 * @jest-environment jsdom
 */
import {
  getCraftOnboardingSeen,
  getDefaultLlmSelection,
  hasSupportedCraftProvider,
  isCraftRecommendedModel,
  isSupportedProviderType,
  resolveSessionLlmSelection,
  setCraftOnboardingSeen,
} from "@/app/craft/onboarding/constants";
import { ModelConfiguration } from "@/lib/languageModels/types";

function model(
  name: string,
  opts: { visible?: boolean; craft?: boolean } = {}
): ModelConfiguration {
  return {
    name,
    is_visible: opts.visible ?? true,
    is_recommended_default: opts.craft ?? false,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    effectiveDisplayName: name,
  };
}

function provider(
  providerType: string,
  models: ModelConfiguration[],
  id: number = 1
) {
  return {
    id,
    name: providerType,
    provider: providerType,
    model_configurations: models,
  };
}

describe("isSupportedProviderType", () => {
  it("recognizes craft provider types", () => {
    expect(isSupportedProviderType("anthropic")).toBe(true);
    expect(isSupportedProviderType("openai")).toBe(true);
    expect(isSupportedProviderType("openrouter")).toBe(true);
    expect(isSupportedProviderType("azure")).toBe(false);
  });
});

describe("hasSupportedCraftProvider", () => {
  it("accepts any configured provider with a visible model", () => {
    expect(
      hasSupportedCraftProvider([provider("azure", [model("gpt-6-sol")])])
    ).toBe(true);
  });

  it("rejects providers without a visible model", () => {
    expect(
      hasSupportedCraftProvider([
        provider("azure", [model("hidden", { visible: false })]),
      ])
    ).toBe(false);
    expect(hasSupportedCraftProvider([])).toBe(false);
    expect(hasSupportedCraftProvider(undefined)).toBe(false);
  });
});

describe("getDefaultLlmSelection", () => {
  it("picks the recommended-default model, skipping earlier providers without one", () => {
    const result = getDefaultLlmSelection([
      {
        ...provider("openai", [model("gpt-6.1-sol", { craft: true })], 2),
        name: "Zulu OpenAI",
      },
      {
        ...provider(
          "bedrock",
          [model("unrecommended"), model("claude-opus-5", { craft: true })],
          3
        ),
        name: "Alpha Bedrock",
      },
      {
        ...provider("anthropic", [model("claude-haiku-4-5")], 1),
        name: "Aardvark Without Recommendations",
      },
    ]);
    expect(result).toEqual({
      providerId: 3,
      providerName: "Alpha Bedrock",
      provider: "bedrock",
      modelName: "claude-opus-5",
    });
  });

  it("falls back to the first visible model by sorted name (matching the backend)", () => {
    const result = getDefaultLlmSelection([
      {
        ...provider(
          "openai",
          [
            model("gpt-6-luna"),
            model("hidden-model", { visible: false }),
            model("gpt-6-astra"),
          ],
          7
        ),
        name: "Self-hosted OpenAI",
      },
    ]);
    // Sorted visible names are [gpt-6-astra, gpt-6-luna] — picked over DB order.
    expect(result).toEqual({
      providerId: 7,
      providerName: "Self-hosted OpenAI",
      provider: "openai",
      modelName: "gpt-6-astra",
    });
  });

  it("returns null when no provider has any visible model", () => {
    const result = getDefaultLlmSelection([
      provider("openai", [model("gpt-6.2-sol", { visible: false })]),
    ]);
    expect(result).toBeNull();
  });

  it("returns null with no providers", () => {
    expect(getDefaultLlmSelection([])).toBeNull();
    expect(getDefaultLlmSelection(undefined)).toBeNull();
  });

  it("prefers the configured default over the recommended model", () => {
    const result = getDefaultLlmSelection(
      [
        provider(
          "anthropic",
          [model("claude-opus-5", { craft: true }), model("claude-haiku-4-5")],
          3
        ),
      ],
      [{ provider_id: 3, model_name: "claude-haiku-4-5" }]
    );
    expect(result).toEqual({
      providerId: 3,
      providerName: "anthropic",
      provider: "anthropic",
      modelName: "claude-haiku-4-5",
    });
  });

  it("ignores a configured default that is not visible", () => {
    const result = getDefaultLlmSelection(
      [
        provider(
          "anthropic",
          [
            model("claude-opus-5", { craft: true }),
            model("claude-haiku-4-5", { visible: false }),
          ],
          3
        ),
      ],
      [{ provider_id: 3, model_name: "claude-haiku-4-5" }]
    );
    expect(result).toEqual({
      providerId: 3,
      providerName: "anthropic",
      provider: "anthropic",
      modelName: "claude-opus-5",
    });
  });

  it("falls through to the next configured default when the first isn't visible or available", () => {
    const result = getDefaultLlmSelection(
      [
        provider(
          "anthropic",
          [model("claude-opus-5", { craft: true }), model("claude-haiku-4-5")],
          3
        ),
      ],
      [
        { provider_id: 99, model_name: "does-not-exist" },
        { provider_id: 3, model_name: "claude-haiku-4-5" },
      ]
    );
    expect(result).toEqual({
      providerId: 3,
      providerName: "anthropic",
      provider: "anthropic",
      modelName: "claude-haiku-4-5",
    });
  });

  it("orders providers by codepoint like the backend, not locale rules", () => {
    // localeCompare puts "aäb" before "azb"; codepoint order ("z" < "ä") —
    // what Python's sorted() uses in _gateway_provider_order — is the reverse.
    const result = getDefaultLlmSelection([
      { ...provider("openai", [model("gpt-6.1-sol")], 1), name: "aäb" },
      { ...provider("openai", [model("gpt-6.2-luna")], 2), name: "azb" },
    ]);
    expect(result?.providerId).toBe(2);
  });
});

describe("isCraftRecommendedModel", () => {
  it("flags the provider's recommended-default model", () => {
    expect(
      isCraftRecommendedModel(model("claude-opus-5", { craft: true }))
    ).toBe(true);
    expect(isCraftRecommendedModel(model("claude-fable-5"))).toBe(false);
  });

  it("does not flag a hidden model even when recommended", () => {
    expect(
      isCraftRecommendedModel(
        model("claude-opus-5", { craft: true, visible: false })
      )
    ).toBe(false);
  });
});

describe("resolveSessionLlmSelection", () => {
  it("decodes a qualified gateway model without losing slashes", () => {
    expect(
      resolveSessionLlmSelection("onyx", "7/anthropic/claude-sonnet", [
        provider("bedrock", [model("anthropic/claude-sonnet")], 7),
      ])
    ).toEqual({
      providerId: 7,
      providerName: "bedrock",
      provider: "bedrock",
      modelName: "anthropic/claude-sonnet",
    });
  });

  it("rejects a stored model that is no longer visible", () => {
    expect(
      resolveSessionLlmSelection("onyx", "7/hidden", [
        provider("bedrock", [model("hidden", { visible: false })], 7),
      ])
    ).toBeNull();
  });

  it("prefers the same-type provider that hosts a legacy session's model", () => {
    expect(
      resolveSessionLlmSelection("openai", "gpt-6.1-sol", [
        provider("openai", [model("gpt-6-astra")], 1),
        provider("openai", [model("gpt-6.1-sol")], 2),
      ])
    ).toEqual({
      providerId: 2,
      providerName: "openai",
      provider: "openai",
      modelName: "gpt-6.1-sol",
    });
  });

  it("falls back to any same-type provider when none hosts the legacy model", () => {
    expect(
      resolveSessionLlmSelection("openai", "gpt-6.1-sol", [
        provider("anthropic", [model("claude-fable-5")], 1),
        provider("openai", [model("gpt-6-astra")], 2),
      ])?.providerId
    ).toBe(2);
  });
});

describe("craft intro seen flag", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("is false before being set and true after", () => {
    expect(getCraftOnboardingSeen("user-1")).toBe(false);
    setCraftOnboardingSeen("user-1");
    expect(getCraftOnboardingSeen("user-1")).toBe(true);
  });

  it("is scoped per user", () => {
    setCraftOnboardingSeen("user-1");
    expect(getCraftOnboardingSeen("user-2")).toBe(false);
  });
});
