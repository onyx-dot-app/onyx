/**
 * @jest-environment jsdom
 */
import {
  getPreferredLlmSelection,
  getStoredRecommendedModelsOnly,
  setStoredLlmSelection,
  setStoredRecommendedModelsOnly,
} from "@/app/craft/utils/llmPreferences";
import { ModelConfiguration } from "@/lib/languageModels/types";

const USER = "user-1";

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

beforeEach(() => {
  window.localStorage.clear();
});

describe("recommended-only toggle", () => {
  it("defaults to true and round-trips", () => {
    expect(getStoredRecommendedModelsOnly(USER)).toBe(true);
    setStoredRecommendedModelsOnly(USER, false);
    expect(getStoredRecommendedModelsOnly(USER)).toBe(false);
    setStoredRecommendedModelsOnly(USER, true);
    expect(getStoredRecommendedModelsOnly(USER)).toBe(true);
  });

  it("is scoped per user", () => {
    setStoredRecommendedModelsOnly(USER, false);
    expect(getStoredRecommendedModelsOnly("user-2")).toBe(true);
  });
});

describe("getPreferredLlmSelection", () => {
  it("prefers the stored selection when still available", () => {
    setStoredLlmSelection(USER, {
      providerId: 2,
      providerName: "openai",
      provider: "openai",
      modelName: "gpt-4o",
    });
    const result = getPreferredLlmSelection(USER, [
      provider("anthropic", [model("claude-opus-5", { craft: true })], 1),
      provider("openai", [model("gpt-4o")], 2),
    ]);
    expect(result?.modelName).toBe("gpt-4o");
  });

  it("does not leak one user's pick to another", () => {
    setStoredLlmSelection(USER, {
      providerId: 2,
      providerName: "openai",
      provider: "openai",
      modelName: "gpt-4o",
    });
    const result = getPreferredLlmSelection("user-2", [
      provider("anthropic", [model("claude-opus-5", { craft: true })], 1),
      provider("openai", [model("gpt-4o")], 2),
    ]);
    expect(result?.modelName).toBe("claude-opus-5");
  });

  it("falls back to the recommended default when the stored model is gone", () => {
    setStoredLlmSelection(USER, {
      providerId: 2,
      providerName: "openai",
      provider: "openai",
      modelName: "removed-model",
    });
    const result = getPreferredLlmSelection(USER, [
      provider("anthropic", [model("claude-opus-5", { craft: true })], 1),
    ]);
    expect(result?.modelName).toBe("claude-opus-5");
  });

  it("ignores corrupt stored values, including parseable non-objects", () => {
    const providers = [
      provider("anthropic", [model("claude-opus-5", { craft: true })], 1),
    ];
    for (const raw of ["not json", "null", '"gpt-4o"', "42"]) {
      window.localStorage.setItem(`onyx:craftLlmSelection:${USER}`, raw);
      expect(getPreferredLlmSelection(USER, providers)?.modelName).toBe(
        "claude-opus-5"
      );
    }
  });

  it("uses the default when no user id is known", () => {
    const result = getPreferredLlmSelection(undefined, [
      provider("anthropic", [model("claude-opus-5", { craft: true })], 1),
    ]);
    expect(result?.modelName).toBe("claude-opus-5");
  });

  it("tries configured defaults in order, falling through unavailable ones", () => {
    const providers = [
      provider(
        "anthropic",
        [model("claude-opus-5", { craft: true }), model("claude-haiku-4-5")],
        3
      ),
    ];
    const result = getPreferredLlmSelection(undefined, providers, [
      { provider_id: 99, model_name: "does-not-exist" },
      { provider_id: 3, model_name: "claude-haiku-4-5" },
    ]);
    expect(result?.modelName).toBe("claude-haiku-4-5");
  });
});
