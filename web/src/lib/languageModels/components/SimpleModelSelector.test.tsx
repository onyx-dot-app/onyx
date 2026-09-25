import React from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import SimpleModelSelector from "@/lib/languageModels/components/SimpleModelSelector";
import type { ModelOptionProvider } from "@/lib/languageModels/types";

// The listbox renders through a portal; keep it inside the test container.
jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));
Element.prototype.scrollIntoView = jest.fn();

const providers: ModelOptionProvider[] = [
  {
    id: 1,
    name: "OpenAI",
    provider: "openai",
    model_configurations: [
      {
        id: 11,
        name: "gpt-4o",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
        supports_reasoning: false,
        effectiveDisplayName: "GPT-4o",
      },
      {
        id: 12,
        name: "gpt-4.1",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: false,
        supports_reasoning: false,
        effectiveDisplayName: "GPT-4.1",
      },
    ],
  },
];

describe("SimpleModelSelector", () => {
  test("nullable: nothing chosen shows the placeholder, never a fallback model", () => {
    render(
      <SimpleModelSelector
        nullable
        providers={providers}
        value={null}
        onChange={jest.fn()}
      />
    );
    expect(screen.getByRole("combobox", { name: "Select model" })).toHaveValue(
      ""
    );
  });

  test("shows the chosen model and emits the picked id", async () => {
    const handleChange = jest.fn();
    const user = setupUser();
    render(
      <SimpleModelSelector
        providers={providers}
        value={11}
        onChange={handleChange}
      />
    );
    expect(screen.getByRole("combobox")).toHaveValue("GPT-4o");

    await user.click(screen.getByRole("combobox"));
    // One provider: no divider, and the list carries a search field.
    expect(screen.queryByText("OpenAI")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Search" })).toHaveFocus();
    await user.click(screen.getByRole("option", { name: /GPT-4\.1/ }));
    expect(handleChange).toHaveBeenCalledWith(12);
  });

  test("non-nullable: re-picking the chosen model changes nothing", async () => {
    const handleChange = jest.fn();
    const user = setupUser();
    render(
      <SimpleModelSelector
        providers={providers}
        value={11}
        onChange={handleChange}
      />
    );
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: /GPT-4o/ }));
    expect(handleChange).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox")).toHaveValue("GPT-4o");
  });

  test("nullable: re-picking the chosen model clears it", async () => {
    const handleChange = jest.fn();
    const user = setupUser();
    render(
      <SimpleModelSelector
        nullable
        providers={providers}
        value={11}
        onChange={handleChange}
      />
    );
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: /GPT-4o/ }));
    expect(handleChange).toHaveBeenCalledWith(null);
  });

  test("groups several providers under foldable dividers, the chosen one open", async () => {
    const user = setupUser();
    const two: ModelOptionProvider[] = [
      ...providers,
      {
        id: 2,
        name: null,
        provider: "anthropic",
        model_configurations: [
          {
            id: 21,
            name: "claude-sonnet-4",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "Claude Sonnet 4",
          },
        ],
      },
    ];
    render(
      <SimpleModelSelector providers={two} value={21} onChange={jest.fn()} />
    );
    await user.click(screen.getByRole("combobox"));
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Claude")).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /Claude Sonnet 4/ })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /GPT-4o/ })
    ).not.toBeInTheDocument();
  });

  test("grouped=false renders every provider's models flat", async () => {
    const user = setupUser();
    render(
      <SimpleModelSelector
        providers={providers}
        value={11}
        onChange={jest.fn()}
        grouped={false}
      />
    );
    await user.click(screen.getByRole("combobox"));
    expect(screen.queryByText("OpenAI")).not.toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  test("renders an empty list without options", async () => {
    const user = setupUser();
    render(
      <SimpleModelSelector
        nullable
        providers={[]}
        value={null}
        onChange={jest.fn()}
      />
    );
    await user.click(screen.getByRole("combobox"));
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });
});
