import { mergeFetchedModelConfigurations } from "@/sections/modals/languageModels/utils";
import type { ModelConfiguration } from "@/lib/languageModels/types";

function makeModel(overrides: Partial<ModelConfiguration>): ModelConfiguration {
  return {
    id: undefined,
    name: "test-model",
    is_visible: true,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    effectiveDisplayName: "test-model",
    ...overrides,
  };
}

describe("mergeFetchedModelConfigurations", () => {
  test("returns fetched list as-is when existing is empty", () => {
    const fetched = [makeModel({ name: "a", supports_image_input: true })];
    const result = mergeFetchedModelConfigurations(fetched, []);
    expect(result).toHaveLength(1);
    expect(result[0]!.name).toBe("a");
  });

  test("preserves is_visible from existing models", () => {
    const existing = [
      makeModel({ name: "a", is_visible: false }),
      makeModel({ name: "b", is_visible: true }),
    ];
    const fetched = [
      makeModel({ name: "a", is_visible: true }),
      makeModel({ name: "b", is_visible: false }),
    ];
    const result = mergeFetchedModelConfigurations(fetched, existing);
    expect(result[0]!.is_visible).toBe(false);
    expect(result[1]!.is_visible).toBe(true);
  });

  test("preserves supports_image_input override from existing models", () => {
    const existing = [
      makeModel({ name: "qwen-vl", supports_image_input: true }),
      makeModel({ name: "qwen-instruct", supports_image_input: false }),
    ];
    const fetched = [
      makeModel({ name: "qwen-vl", supports_image_input: false }),
      makeModel({ name: "qwen-instruct", supports_image_input: false }),
    ];
    const result = mergeFetchedModelConfigurations(fetched, existing);
    expect(result[0]!.supports_image_input).toBe(true);
    expect(result[1]!.supports_image_input).toBe(false);
  });

  test("new models from fetch are added with is_visible=false", () => {
    const existing = [makeModel({ name: "a", is_visible: true })];
    const fetched = [
      makeModel({ name: "a", is_visible: true }),
      makeModel({ name: "b", is_visible: true }),
    ];
    const result = mergeFetchedModelConfigurations(fetched, existing);
    expect(result[1]!.is_visible).toBe(false);
  });
});
