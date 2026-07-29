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
  recommended = false,
  vendor?: string
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
    vendor,
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

describe("BuildLLMPopover aggregator vendors", () => {
  const bedrock: LLMProviderDescriptor[] = [
    {
      id: 21,
      name: null,
      provider: "bedrock",
      provider_display_name: "Amazon Bedrock",
      model_configurations: [
        model("openai.gpt-oss-120b", "GPT OSS 120B", true, "OpenAI"),
        model("meta.llama3-70b", "Llama 3 70B", true, "Meta"),
        model("zai.glm-4.6", "GLM 4.6", true, "ZAI"),
      ],
    },
  ];

  it("splits a Bedrock provider into one group per hosted vendor", () => {
    const onSelectionChange = jest.fn();
    render(
      <BuildLLMPopover
        currentSelection={null}
        onSelectionChange={onSelectionChange}
        llmProviders={bedrock}
      >
        <button>Choose model</button>
      </BuildLLMPopover>
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose model" }));

    expect(
      screen.getAllByText(/^Amazon Bedrock\//).map((label) => label.textContent)
    ).toEqual([
      "Amazon Bedrock/Meta",
      "Amazon Bedrock/OpenAI",
      "Amazon Bedrock/ZAI",
    ]);

    fireEvent.click(
      screen.getByRole("button", { name: /Amazon Bedrock\/Meta/ })
    );

    expect(screen.getByText("Llama 3 70B")).toBeInTheDocument();
    expect(screen.queryByText("GLM 4.6")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Llama 3 70B/ }));
    expect(onSelectionChange).toHaveBeenCalledWith({
      providerId: 21,
      providerName: "",
      provider: "bedrock",
      modelName: "meta.llama3-70b",
    });
  });

  it("keeps vendorless aggregator models under the plain provider group", () => {
    const mixed: LLMProviderDescriptor[] = [
      {
        id: 22,
        name: null,
        provider: "bedrock",
        provider_display_name: "Amazon Bedrock",
        model_configurations: [
          model("meta.llama3-70b", "Llama 3 70B", true, "Meta"),
          model("custom-imported-model", "Custom Imported", true),
        ],
      },
    ];

    render(
      <BuildLLMPopover
        currentSelection={null}
        onSelectionChange={jest.fn()}
        llmProviders={mixed}
      >
        <button>Choose model</button>
      </BuildLLMPopover>
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose model" }));

    expect(screen.getByText("Amazon Bedrock/Meta")).toBeInTheDocument();
    expect(screen.getByText("Amazon Bedrock")).toBeInTheDocument();
  });

  it("does not split a non-aggregator provider that reports a vendor", () => {
    const anthropic: LLMProviderDescriptor[] = [
      {
        id: 23,
        name: null,
        provider: "anthropic",
        provider_display_name: "Anthropic",
        model_configurations: [
          model("claude-opus-4-7", "Claude Opus 4.7", true, "Anthropic"),
        ],
      },
    ];

    render(
      <BuildLLMPopover
        currentSelection={null}
        onSelectionChange={jest.fn()}
        llmProviders={anthropic}
      >
        <button>Choose model</button>
      </BuildLLMPopover>
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose model" }));

    expect(screen.getByText("Anthropic")).toBeInTheDocument();
    expect(screen.queryByText("Anthropic/Anthropic")).not.toBeInTheDocument();
  });

  it("auto-expands the vendor group holding the current selection", () => {
    render(
      <BuildLLMPopover
        currentSelection={{
          providerId: 21,
          providerName: "",
          provider: "bedrock",
          modelName: "zai.glm-4.6",
        }}
        onSelectionChange={jest.fn()}
        llmProviders={bedrock}
      >
        <button>Choose model</button>
      </BuildLLMPopover>
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose model" }));

    expect(screen.getByText("GLM 4.6")).toBeInTheDocument();
    expect(screen.queryByText("Llama 3 70B")).not.toBeInTheDocument();
  });
});
