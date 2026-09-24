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
  { value: "apple", label: "Apple" },
  { value: "banana", label: "Banana" },
  { value: "cherry", label: "Cherry" },
];

const mockOptionsWithDescriptions = [
  { value: "apple", label: "Apple", description: "A red fruit" },
  { value: "banana", label: "Banana", description: "A yellow fruit" },
];

function setupUser() {
  return userEvent.setup({ delay: null });
}

describe("InputSingleSelect", () => {
  describe("Rendering and picking", () => {
    const sectionedOptions = [
      { options: [{ value: "none", label: "Do not re-index" }] },
      {
        label: "Re-index options",
        options: [
          { value: "reindex", label: "Re-index all" },
          { value: "instant", label: "Switch first" },
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

    test("renders sectioned options with a titled divider", async () => {
      const user = setupUser();
      render(
        <InputSingleSelect
          placeholder="Choose a strategy"
          value=""
          options={sectionedOptions}
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

    test("re-picking a non-default selected option falls back to the default", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputSingleSelect
          defaultOption="apple"
          value="banana"
          onValueChange={handleValueChange}
          options={mockOptions}
        />
      );
      await user.click(screen.getByRole("combobox"));
      await user.click(screen.getByRole("option", { name: /Banana/ }));
      expect(handleValueChange).toHaveBeenCalledWith("apple");
      expect(handleValueChange).not.toHaveBeenCalledWith("");
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
