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
