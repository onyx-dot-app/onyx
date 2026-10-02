import { diffModelConfigurations } from "@/sections/modals/languageModels/utils";
import type { ModelConfiguration } from "@/lib/languageModels/types";

function model(
  id: number,
  name: string,
  isVisible: boolean
): ModelConfiguration {
  return {
    id,
    name,
    is_visible: isVisible,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    display_name: name,
    effectiveDisplayName: name,
  };
}

describe("diffModelConfigurations", () => {
  test("sends edited and new models and names the dropped ones", () => {
    const server = [model(1, "alpha", true), model(2, "beta", true)];
    const form = [
      { ...server[0]! },
      { ...server[1]!, is_visible: false },
      model(0, "added", true),
    ];
    expect(diffModelConfigurations(form, server)).toEqual({
      changed: [form[1], form[2]],
      removedNames: [],
    });
    expect(diffModelConfigurations([server[0]!], server)).toEqual({
      changed: [],
      removedNames: ["beta"],
    });
  });
});
