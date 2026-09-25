import React from "react";
import { render, screen, fireEvent, waitFor } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { InputSingleSelect } from "./components";

// Mock createPortal for dropdown rendering
jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

const mockOptions = [
  { value: "apple", title: "Apple" },
  { value: "banana", title: "Banana" },
  { value: "cherry", title: "Cherry" },
];

const mockOptionsWithDescriptions = [
  { value: "apple", title: "Apple", description: "A red fruit" },
  { value: "banana", title: "Banana", description: "A yellow fruit" },
];

function setupUser() {
  return userEvent.setup({ delay: null });
}

describe("InputSingleSelect", () => {
  describe("Search and foldable dividers", () => {
    const providerOptions = [
      {
        title: "OpenAI",
        foldable: true,
        options: [
          { value: "gpt-4o", title: "GPT-4o" },
          { value: "gpt-4.1", title: "GPT-4.1" },
        ],
      },
      {
        title: "Anthropic",
        foldable: true,
        options: [{ value: "claude", title: "Claude Sonnet" }],
      },
    ];

    test("search: the search field takes focus and filters the rows", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          search
          placeholder="Model"
          value=""
          options={mockOptions}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Model" }));
      const search = screen.getByRole("textbox", { name: "Search" });
      expect(search).toHaveFocus();
      expect(screen.getAllByRole("option")).toHaveLength(3);

      await user.type(search, "ban");
      expect(screen.getAllByRole("option")).toHaveLength(1);
      expect(
        screen.getByRole("option", { name: /Banana/ })
      ).toBeInTheDocument();
    });

    test("search: Escape closes the list and returns focus to the trigger", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          search
          placeholder="Model"
          value=""
          options={mockOptions}
        />
      );
      const trigger = screen.getByRole("combobox", { name: "Model" });
      await user.click(trigger);
      await user.keyboard("{Escape}");
      await waitFor(() => {
        expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      });
      expect(trigger).toHaveFocus();
    });

    test("Enter on the closed trigger opens the list", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect placeholder="Model" value="" options={mockOptions} />
      );
      screen.getByRole("combobox", { name: "Model" }).focus();
      await user.keyboard("{Enter}");
      expect(screen.getByRole("listbox")).toBeInTheDocument();
    });

    test("Tab and the arrows walk the stops and wrap around", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Model"
          value=""
          onValueChange={handleValueChange}
          options={mockOptions}
        />
      );
      screen.getByRole("combobox", { name: "Model" }).focus();
      await user.keyboard("{Enter}");
      // Nothing highlighted yet; Tab lands on the first row.
      await user.keyboard("{Tab}");
      expect(screen.getByRole("option", { name: /Apple/ })).toHaveAttribute(
        "data-highlighted"
      );
      // Shift+Tab from the first row wraps to the last.
      await user.keyboard("{Shift>}{Tab}{/Shift}");
      expect(screen.getByRole("option", { name: /Cherry/ })).toHaveAttribute(
        "data-highlighted"
      );
      // ArrowDown from the last wraps to the first; Enter picks it.
      await user.keyboard("{ArrowDown}{Enter}");
      expect(handleValueChange).toHaveBeenCalledWith("apple");
    });

    test("with a search field, the cycle passes through it and typing never highlights", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          search
          placeholder="Model"
          value=""
          options={mockOptions}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Model" }));
      const searchField = screen.getByRole("textbox", { name: "Search" });
      await user.type(searchField, "a");
      expect(
        screen
          .queryAllByRole("option")
          .filter((o) => o.hasAttribute("data-highlighted"))
      ).toHaveLength(0);
      // Shift+Tab from the search field wraps to the last visible row.
      await user.keyboard("{Shift>}{Tab}{/Shift}");
      expect(screen.getByRole("option", { name: /Banana/ })).toHaveAttribute(
        "data-highlighted"
      );
      // Tab from the last row returns to the search field: no row highlighted.
      await user.keyboard("{Tab}");
      expect(
        screen
          .queryAllByRole("option")
          .filter((o) => o.hasAttribute("data-highlighted"))
      ).toHaveLength(0);
      expect(searchField).toHaveFocus();
    });

    test("Enter on a foldable divider's title toggles it", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Model"
          value=""
          options={providerOptions}
        />
      );
      screen.getByRole("combobox", { name: "Model" }).focus();
      await user.keyboard("{Enter}");
      expect(screen.queryAllByRole("option")).toHaveLength(0);
      // The first stop is the OpenAI title; Enter opens it.
      await user.keyboard("{Tab}{Enter}");
      expect(screen.getAllByRole("option")).toHaveLength(2);
      await user.keyboard("{Enter}");
      expect(screen.queryAllByRole("option")).toHaveLength(0);
    });

    test("a foldable divider starts folded unless it holds the selection", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Model"
          value="claude"
          options={providerOptions}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Model" }));
      expect(
        screen.getByRole("option", { name: /Claude/ })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("option", { name: /GPT-4o/ })
      ).not.toBeInTheDocument();
      expect(screen.getByText("OpenAI")).toBeInTheDocument();
    });

    test("clicking a foldable divider's title keeps the list open", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Model"
          value=""
          options={providerOptions}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Model" }));
      await user.click(screen.getByText("OpenAI"));
      expect(screen.getByRole("listbox")).toBeInTheDocument();
      expect(screen.getAllByRole("option")).toHaveLength(2);
    });

    test("clicking a foldable divider's title toggles its rows", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Model"
          value=""
          options={providerOptions}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Model" }));
      expect(screen.queryAllByRole("option")).toHaveLength(0);
      await user.click(screen.getByText("OpenAI"));
      expect(screen.getAllByRole("option")).toHaveLength(2);
      await user.click(screen.getByText("OpenAI"));
      expect(screen.queryAllByRole("option")).toHaveLength(0);
    });

    test("a term matching a divider's title keeps its whole section", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          search
          placeholder="Model"
          value=""
          options={providerOptions}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Model" }));
      await user.type(screen.getByRole("textbox", { name: "Search" }), "open");
      expect(screen.getAllByRole("option")).toHaveLength(2);
      expect(screen.queryByText("Anthropic")).not.toBeInTheDocument();
    });

    test("searching opens folded groups to show their matches", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          search
          placeholder="Model"
          value=""
          options={providerOptions}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Model" }));
      expect(screen.queryAllByRole("option")).toHaveLength(0);
      await user.type(
        screen.getByRole("textbox", { name: "Search" }),
        "claude"
      );
      expect(screen.getAllByRole("option")).toHaveLength(1);
      expect(screen.queryByText("OpenAI")).not.toBeInTheDocument();
    });
  });

  describe("Rendering and picking", () => {
    const dividedOptions = [
      { value: "none", title: "Do not re-index" },
      {
        title: "Re-index options",
        options: [
          { value: "reindex", title: "Re-index all" },
          { value: "instant", title: "Switch first" },
        ],
      },
    ];

    test("renders a read-only trigger showing the selected label", () => {
      render(
        <InputSingleSelect
          placeholder="Select a fruit"
          value="banana"
          options={mockOptions}
        />
      );
      const input = screen.getByPlaceholderText("Select a fruit");
      expect(input).toHaveAttribute("readonly");
      expect(input).toHaveValue("Banana");
      expect(input).not.toHaveAttribute("aria-autocomplete");
    });

    test("opens on click and lists every option, ignoring keystrokes", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Select a fruit"
          value="banana"
          options={mockOptions}
        />
      );
      const input = screen.getByPlaceholderText("Select a fruit");
      await user.click(input);
      expect(screen.getAllByRole("option")).toHaveLength(3);

      await user.keyboard("ap");
      expect(input).toHaveValue("Banana");
      expect(screen.getAllByRole("option")).toHaveLength(3);
    });

    test("a second click closes it, and focus alone does not open it", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Select a fruit"
          value="banana"
          options={mockOptions}
        />
      );
      const input = screen.getByPlaceholderText("Select a fruit");
      await user.tab();
      expect(input).toHaveFocus();
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

      await user.click(input);
      expect(screen.getByRole("listbox")).toBeInTheDocument();
      await user.click(input);
      await waitFor(() => {
        expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      });
    });

    test("an untitled divider renders a plain line between its rows and the loose ones", async () => {
      const user = setupUser();
      const { container } = render(
        <InputSingleSelect
          placeholder="Choose a strategy"
          value=""
          options={[
            { value: "none", title: "Do not re-index" },
            {
              options: [
                { value: "reindex", title: "Re-index all" },
                { value: "instant", title: "Switch first" },
              ],
            },
          ]}
        />
      );
      await user.click(screen.getByPlaceholderText("Choose a strategy"));
      expect(screen.getAllByRole("option")).toHaveLength(3);
      expect(container.querySelectorAll(".opal-divider")).toHaveLength(1);
      expect(container.querySelector(".opal-divider-title")).toBeNull();
    });

    test("the trigger shows the chosen option's icon", () => {
      function Swatch(props: React.SVGProps<SVGSVGElement>) {
        return <svg data-testid="swatch" {...props} />;
      }
      const { rerender } = render(
        <InputSingleSelect
          placeholder="Color mode"
          value="dark"
          options={[
            { value: "light", title: "Light" },
            { value: "dark", title: "Dark", icon: Swatch },
          ]}
        />
      );
      expect(screen.getByTestId("swatch")).toBeInTheDocument();
      rerender(
        <InputSingleSelect
          placeholder="Color mode"
          value="light"
          options={[
            { value: "light", title: "Light" },
            { value: "dark", title: "Dark", icon: Swatch },
          ]}
        />
      );
      expect(screen.queryByTestId("swatch")).not.toBeInTheDocument();
    });

    test("renders a loose option and a titled divider", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Choose a strategy"
          value=""
          options={dividedOptions}
        />
      );
      await user.click(screen.getByPlaceholderText("Choose a strategy"));
      expect(screen.getByText("Re-index options")).toBeInTheDocument();
      expect(screen.getAllByRole("option")).toHaveLength(3);
    });

    test("picking an option emits it and closes", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Select a fruit"
          value=""
          onValueChange={handleValueChange}
          options={mockOptions}
        />
      );
      await user.click(screen.getByPlaceholderText("Select a fruit"));
      await user.click(screen.getByRole("option", { name: /Cherry/ }));
      expect(handleValueChange).toHaveBeenCalledWith("cherry");
      await waitFor(() => {
        expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      });
    });
  });

  describe("Default option", () => {
    test("shows the default at rest when the value is empty", () => {
      render(
        <InputSingleSelect
          defaultOption="apple"
          placeholder="Select an option"
          value=""
          options={mockOptions}
        />
      );
      expect(screen.getByRole("combobox")).toHaveValue("Apple");
    });

    test("picking the displayed default commits it when the value is empty", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputSingleSelect
          defaultOption="apple"
          placeholder="Select an option"
          value=""
          onValueChange={handleValueChange}
          options={mockOptions}
        />
      );
      await user.click(screen.getByRole("combobox"));
      await user.click(screen.getByRole("option", { name: /Apple/ }));
      expect(handleValueChange).toHaveBeenCalledWith("apple");
    });

    test("a strict value outside the set shows the placeholder, not the value", () => {
      render(
        <InputSingleSelect
          placeholder="Select a fruit"
          value="kiwi"
          options={mockOptions}
        />
      );
      expect(screen.getByPlaceholderText("Select a fruit")).toHaveValue("");
    });

    test("re-picking the default itself does nothing", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputSingleSelect
          defaultOption="apple"
          placeholder="Select an option"
          value="apple"
          onValueChange={handleValueChange}
          options={mockOptions}
        />
      );
      await user.click(screen.getByRole("combobox"));
      await user.click(screen.getByRole("option", { name: /Apple/ }));
      expect(handleValueChange).not.toHaveBeenCalled();
      await waitFor(() => {
        expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      });
      expect(screen.getByRole("combobox")).toHaveValue("Apple");
    });

    test("with a default, re-picking a non-default selected option does nothing", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputSingleSelect
          defaultOption="apple"
          placeholder="Select an option"
          value="banana"
          onValueChange={handleValueChange}
          options={mockOptions}
        />
      );
      await user.click(screen.getByRole("combobox"));
      await user.click(screen.getByRole("option", { name: /Banana/ }));
      expect(handleValueChange).not.toHaveBeenCalled();
      await waitFor(() => {
        expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      });
      expect(screen.getByRole("combobox")).toHaveValue("Banana");
    });

    test("without a default, re-picking the selected option unselects it", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Select a fruit"
          value="banana"
          onValueChange={handleValueChange}
          options={mockOptions}
        />
      );
      await user.click(screen.getByRole("combobox"));
      await user.click(screen.getByRole("option", { name: /Banana/ }));
      expect(handleValueChange).toHaveBeenCalledWith("");
    });
  });
});
