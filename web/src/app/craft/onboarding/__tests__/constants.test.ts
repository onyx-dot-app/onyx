import {
  craftModelName,
  getDefaultLlmSelection,
  hasSupportedCraftProvider,
  isSupportedProviderType,
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

function provider(providerType: string, models: ModelConfiguration[]) {
  return {
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
  it("is true when a configured provider is a craft type", () => {
    expect(hasSupportedCraftProvider([{ provider: "anthropic" }])).toBe(true);
  });

  it("is false for unsupported-only or empty/undefined", () => {
    expect(hasSupportedCraftProvider([{ provider: "azure" }])).toBe(false);
    expect(hasSupportedCraftProvider([])).toBe(false);
    expect(hasSupportedCraftProvider(undefined)).toBe(false);
  });
});

describe("craftModelName", () => {
  it("prefers the is_recommended_default model", () => {
    expect(craftModelName([model("a"), model("b", { craft: true })])).toBe("b");
  });

  it("falls back to the first visible model", () => {
    expect(
      craftModelName([model("hidden", { visible: false }), model("v")])
    ).toBe("v");
  });

  it("returns null when nothing is visible or recommended", () => {
    expect(craftModelName([model("hidden", { visible: false })])).toBeNull();
    expect(craftModelName([])).toBeNull();
  });
});

describe("getDefaultLlmSelection", () => {
  it("picks the highest-priority craft provider (anthropic) with its recommended model", () => {
    const result = getDefaultLlmSelection([
      provider("openai", [model("gpt-5.5", { craft: true })]),
      provider("anthropic", [
        model("claude-opus-4-8", { craft: true }),
        model("claude-sonnet-4-6"),
      ]),
    ]);
    expect(result).toEqual({
      providerName: "anthropic",
      provider: "anthropic",
      modelName: "claude-opus-4-8",
    });
  });

  it("falls back to first visible model when no is_recommended_default flag", () => {
    const result = getDefaultLlmSelection([
      provider("openai", [model("gpt-5.5")]),
    ]);
    expect(result?.modelName).toBe("gpt-5.5");
  });

  it("returns null with no providers", () => {
    expect(getDefaultLlmSelection([])).toBeNull();
    expect(getDefaultLlmSelection(undefined)).toBeNull();
  });
});
