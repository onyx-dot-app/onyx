import { fireEvent, render, screen } from "@testing-library/react";
import { BuildLLMPopover } from "@/app/craft/components/BuildLLMPopover";
import type {
  LLMProviderDescriptor,
  ModelConfiguration,
} from "@/lib/languageModels/types";

jest.mock("@/lib/hooks/useLLMProviderOptions", () => ({
  useLLMProviderOptions: () => ({ llmProviderOptions: [] }),
}));

Element.prototype.scrollIntoView = jest.fn();

function model(
  name: string,
  displayName: string,
  recommended = false
): ModelConfiguration {
  return {
    name,
    display_name: displayName,
    effectiveDisplayName: displayName,
    is_visible: true,
    is_recommended_default: recommended,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: true,
  };
}

const providers: LLMProviderDescriptor[] = [
  {
    id: 13,
    name: "OpenAI Team",
    provider: "openai_compatible",
    provider_display_name: "OpenAI Compatible",
    model_configurations: [
      model("gpt-5.6-sol", "GPT-5.6 Sol", true),
      model("gpt-5.5", "GPT-5.5", true),
      model("gpt-5-mini", "GPT-5 Mini"),
    ],
  },
  {
    id: 14,
    name: "Legacy Models",
    provider: "anthropic",
    provider_display_name: "Anthropic",
    model_configurations: [model("claude-haiku-4-5", "Claude Haiku 4.5")],
  },
];

describe("BuildLLMPopover recommended models", () => {
  it("groups all recommended models under configured providers and omits empty providers", () => {
    render(
      <BuildLLMPopover
        currentSelection={null}
        onSelectionChange={jest.fn()}
        llmProviders={providers}
      >
        <button>Choose model</button>
      </BuildLLMPopover>
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose model" }));

    const provider = screen.getByRole("button", { name: /OpenAI Team/ });
    expect(provider).toBeInTheDocument();
    expect(screen.queryByText("Legacy Models")).not.toBeInTheDocument();

    fireEvent.click(provider);

    expect(screen.getByText("GPT-5.6 Sol")).toBeInTheDocument();
    expect(screen.getByText("GPT-5.5")).toBeInTheDocument();
    expect(screen.queryByText("GPT-5 Mini")).not.toBeInTheDocument();
  });
});
