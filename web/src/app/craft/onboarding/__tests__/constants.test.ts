/**
 * @jest-environment jsdom
 */
import {
  CRAFT_RECOMMENDED_MODEL_NAMES,
  craftRecommendedModels,
  getCraftOnboardingSeen,
  getDefaultLlmSelection,
  hasSupportedCraftProvider,
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
      hasSupportedCraftProvider([provider("azure", [model("gpt-5")])])
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
  it("picks the first recommended model from the first alphabetical provider", () => {
    const result = getDefaultLlmSelection([
      {
        ...provider("openai", [model("gpt-5.5")], 2),
        name: "Zulu OpenAI",
      },
      {
        ...provider(
          "bedrock",
          [model("unrecommended"), model("claude-opus-4-8")],
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
      modelName: "claude-opus-4-8",
    });
  });

  it("falls back to the first visible model when nothing matches the curated list", () => {
    const result = getDefaultLlmSelection([
      {
        ...provider(
          "openai",
          [model("hidden-model", { visible: false }), model("gpt-4o")],
          7
        ),
        name: "Self-hosted OpenAI",
      },
    ]);
    expect(result).toEqual({
      providerId: 7,
      providerName: "Self-hosted OpenAI",
      provider: "openai",
      modelName: "gpt-4o",
    });
  });

  it("returns null when no provider has any visible model", () => {
    const result = getDefaultLlmSelection([
      provider("openai", [model("gpt-5-mini", { visible: false })]),
    ]);
    expect(result).toBeNull();
  });

  it("returns null with no providers", () => {
    expect(getDefaultLlmSelection([])).toBeNull();
    expect(getDefaultLlmSelection(undefined)).toBeNull();
  });

  it("orders providers by codepoint like the backend, not locale rules", () => {
    // localeCompare puts "aäb" before "azb"; codepoint order ("z" < "ä") —
    // what Python's sorted() uses in _gateway_provider_order — is the reverse.
    const result = getDefaultLlmSelection([
      { ...provider("openai", [model("gpt-5.5")], 1), name: "aäb" },
      { ...provider("openai", [model("gpt-5.6-sol")], 2), name: "azb" },
    ]);
    expect(result?.providerId).toBe(2);
  });
});

describe("craftRecommendedModels", () => {
  it("uses the explicit six-model Craft allowlist", () => {
    const names = [
      "gpt-5.6-sol",
      "gpt-5.5",
      "claude-fable-5",
      "claude-opus-4-8",
      "moonshotai/kimi-k3",
      "z-ai/glm-5.2",
    ];
    const models = [
      ...names.map((name) => model(name)),
      model("gpt-5.6-terra"),
      model("claude-haiku-4-5"),
    ];

    expect([...CRAFT_RECOMMENDED_MODEL_NAMES]).toEqual(names);
    expect(craftRecommendedModels(models).map(({ name }) => name)).toEqual(
      names
    );
  });

  it("omits hidden allowlisted models", () => {
    expect(
      craftRecommendedModels([
        model("gpt-5.5", { visible: false }),
        model("gpt-5.6-sol"),
      ]).map(({ name }) => name)
    ).toEqual(["gpt-5.6-sol"]);
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
      resolveSessionLlmSelection("openai", "gpt-5.5", [
        provider("openai", [model("gpt-4o")], 1),
        provider("openai", [model("gpt-5.5")], 2),
      ])
    ).toEqual({
      providerId: 2,
      providerName: "openai",
      provider: "openai",
      modelName: "gpt-5.5",
    });
  });

  it("falls back to any same-type provider when none hosts the legacy model", () => {
    expect(
      resolveSessionLlmSelection("openai", "gpt-5.5", [
        provider("anthropic", [model("claude-fable-5")], 1),
        provider("openai", [model("gpt-4o")], 2),
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
