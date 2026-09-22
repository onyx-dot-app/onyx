import { getModelIcon } from "@/lib/languageModels";
import { LLMProviderName } from "@/lib/languageModels/types";
import { SvgClaude, SvgGemini, SvgVenice } from "@opal/logos";

describe("getModelIcon", () => {
  // Venice serves Anthropic, Google and open-source models alongside its own,
  // so the vendor has to win over the provider. Without Venice in
  // AGGREGATOR_PROVIDERS the provider-name branch matches first and every
  // model in the picker wears the Venice keys.
  it("prefers the vendor mark for models Venice hosts", () => {
    expect(getModelIcon(LLMProviderName.VENICE, "claude-opus-4-5")).toBe(
      SvgClaude
    );
    expect(getModelIcon(LLMProviderName.VENICE, "gemini-3-6-flash")).toBe(
      SvgGemini
    );
  });

  it("falls back to the Venice mark for Venice's own models", () => {
    expect(getModelIcon(LLMProviderName.VENICE, "venice-uncensored-1-2")).toBe(
      SvgVenice
    );
  });
});
