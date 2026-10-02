import React from "react";
import { fireEvent, render, screen, setupUser } from "@tests/setup/test-utils";
import SimpleModelSelector from "@/lib/languageModels/components/SimpleModelSelector";
import { SERVER_SEARCH_DEBOUNCE_MS } from "@/lib/languageModels/hooks";
import type {
  ModelOptionProvider,
  ModelPaging,
} from "@/lib/languageModels/types";

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

  test("globalDefault: null shows the Global Default row, which names the fallback", async () => {
    const handleChange = jest.fn();
    const user = setupUser();
    render(
      <SimpleModelSelector
        nullable
        globalDefault={{ description: "GPT-4o" }}
        providers={providers}
        value={null}
        onChange={handleChange}
      />
    );
    expect(screen.getByRole("combobox")).toHaveValue("Global Default");

    await user.click(screen.getByRole("combobox"));
    const row = screen.getByRole("option", { name: /Global Default/ });
    expect(row).toHaveTextContent("GPT-4o");
    // Re-picking the row is a no-op: null has nothing to clear into.
    await user.click(row);
    expect(handleChange).not.toHaveBeenCalled();
  });

  test("globalDefault: picking a model emits its id, picking the row emits null", async () => {
    const handleChange = jest.fn();
    const user = setupUser();
    const { rerender } = render(
      <SimpleModelSelector
        nullable
        globalDefault={{}}
        providers={providers}
        value={null}
        onChange={handleChange}
      />
    );
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: /GPT-4\.1/ }));
    expect(handleChange).toHaveBeenLastCalledWith(12);

    rerender(
      <SimpleModelSelector
        nullable
        globalDefault={{}}
        providers={providers}
        value={12}
        onChange={handleChange}
      />
    );
    expect(screen.getByRole("combobox")).toHaveValue("GPT-4.1");
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: /Global Default/ }));
    expect(handleChange).toHaveBeenLastCalledWith(null);
  });

  test("disabled: the field does not open", async () => {
    const user = setupUser();
    render(
      <SimpleModelSelector
        providers={providers}
        value={11}
        onChange={jest.fn()}
        disabled
      />
    );
    await user.click(screen.getByRole("combobox"));
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  test("modelPaging: the end of the list loads more, a miss searches the server", async () => {
    jest.useFakeTimers();
    const user = setupUser({ advanceTimers: jest.advanceTimersByTime });
    const modelPaging: ModelPaging = {
      hasMore: true,
      isLoading: false,
      loadMore: jest.fn().mockResolvedValue(undefined),
      search: jest.fn().mockResolvedValue(true),
      searchHasMore: false,
      loadMoreSearch: jest.fn().mockResolvedValue(undefined),
    };
    try {
      render(
        <SimpleModelSelector
          providers={providers}
          value={11}
          onChange={jest.fn()}
          modelPaging={modelPaging}
        />
      );
      await user.click(screen.getByRole("combobox"));
      // jsdom lays nothing out, so any scroll lands at the end of the rows.
      fireEvent.scroll(
        screen
          .getByRole("listbox")
          .querySelector(".opal-select-dropdown-scroll")!
      );
      // One page request per scroll, for the providers whose rows are on show.
      expect(modelPaging.loadMore).toHaveBeenCalledTimes(1);
      expect(modelPaging.loadMore).toHaveBeenCalledWith([1]);

      const search = screen.getByRole("textbox", { name: "Search" });
      await user.type(search, "gpt");
      jest.advanceTimersByTime(SERVER_SEARCH_DEBOUNCE_MS);
      expect(modelPaging.search).not.toHaveBeenCalled();

      await user.clear(search);
      await user.type(search, "claude");
      jest.advanceTimersByTime(SERVER_SEARCH_DEBOUNCE_MS);
      // Every provider with unloaded models, so no provider ids.
      expect(modelPaging.search).toHaveBeenCalledWith("claude", undefined);

      // Clearing forgets the query, so the same miss searches again.
      await user.clear(search);
      await user.type(search, "claude");
      jest.advanceTimersByTime(SERVER_SEARCH_DEBOUNCE_MS);
      expect(modelPaging.search).toHaveBeenCalledTimes(2);
    } finally {
      jest.useRealTimers();
    }
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
