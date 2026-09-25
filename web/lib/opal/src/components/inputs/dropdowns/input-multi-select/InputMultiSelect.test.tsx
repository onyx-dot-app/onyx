import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { InputMultiSelect } from "./components";

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
];

function setupUser() {
  return userEvent.setup({ delay: null });
}

describe("InputMultiSelect", () => {
  describe("Search", () => {
    test("search: the search field filters the rows and a pick keeps the list open", async () => {
      const handleSelect = jest.fn();
      const user = setupUser();
      render(
        <InputMultiSelect
          search
          tags={[]}
          options={mockOptions}
          placeholder="Pick"
          onSelectOption={handleSelect}
          onRemoveTag={jest.fn()}
        />
      );
      await user.click(screen.getByRole("combobox", { name: "Pick" }));
      const search = screen.getByRole("textbox", { name: "Search" });
      expect(search).toHaveFocus();
      await user.type(search, "ban");
      expect(screen.getAllByRole("option")).toHaveLength(1);
      await user.click(screen.getByRole("option", { name: /Banana/ }));
      expect(handleSelect).toHaveBeenCalledWith(
        expect.objectContaining({ value: "banana" })
      );
      expect(screen.getByRole("listbox")).toBeInTheDocument();
    });
  });

  describe("Keyboard removal", () => {
    test("Backspace on the closed field arms the last chip, then removes chips one by one", async () => {
      const handleRemove = jest.fn();
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[
            { id: "apple", label: "Apple" },
            { id: "banana", label: "Banana" },
          ]}
          options={mockOptions}
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onRemoveTag={handleRemove}
        />
      );
      screen.getByRole("combobox", { name: "Pick" }).focus();
      await user.keyboard("{Backspace}");
      expect(screen.getByRole("button", { name: /Banana/ })).toHaveFocus();
      await user.keyboard("{Backspace}");
      expect(handleRemove).toHaveBeenCalledWith("banana");
    });

    test("the arrows walk the chips and Tab leaves the field", async () => {
      const user = setupUser();
      render(
        <>
          <InputMultiSelect
            tags={[
              { id: "apple", label: "Apple" },
              { id: "banana", label: "Banana" },
            ]}
            options={mockOptions}
            placeholder="Pick"
            onSelectOption={jest.fn()}
            onRemoveTag={jest.fn()}
          />
          <button type="button">After</button>
        </>
      );
      const field = screen.getByRole("combobox", { name: "Pick" });
      field.focus();
      await user.keyboard("{ArrowLeft}");
      expect(screen.getByRole("button", { name: /Banana/ })).toHaveFocus();
      await user.keyboard("{ArrowLeft}");
      expect(screen.getByRole("button", { name: /Apple/ })).toHaveFocus();
      await user.keyboard("{ArrowRight}{ArrowRight}");
      expect(field).toHaveFocus();
      // Chips are not Tab stops.
      await user.keyboard("{Tab}");
      expect(screen.getByRole("button", { name: "After" })).toHaveFocus();
    });
  });

  describe("Rendering and picking", () => {
    test("a chip shows its option's icon", () => {
      function Swatch(props: React.SVGProps<SVGSVGElement>) {
        return <svg data-testid="swatch" {...props} />;
      }
      render(
        <InputMultiSelect
          tags={[{ id: "apple", label: "Apple" }]}
          options={[
            { value: "apple", title: "Apple", icon: Swatch },
            { value: "banana", title: "Banana" },
          ]}
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onRemoveTag={jest.fn()}
        />
      );
      expect(screen.getByTestId("swatch")).toBeInTheDocument();
    });

    test("renders no text input and opens from the combobox element", async () => {
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[]}
          options={mockOptions}
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onRemoveTag={jest.fn()}
        />
      );

      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      const trigger = screen.getByRole("combobox", { name: "Pick" });
      expect(trigger).toHaveTextContent("Pick");

      await user.click(trigger);
      expect(screen.getAllByRole("option")).toHaveLength(2);
    });

    test("a second click closes it, and focus alone does not open it", async () => {
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[]}
          options={mockOptions}
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onRemoveTag={jest.fn()}
        />
      );
      const trigger = screen.getByRole("combobox", { name: "Pick" });
      await user.tab();
      expect(trigger).toHaveFocus();
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

      await user.click(trigger);
      expect(screen.getByRole("listbox")).toBeInTheDocument();
      await user.click(trigger);
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });

    test("arrow keys and Enter pick an option", async () => {
      const handleSelectOption = jest.fn();
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[]}
          options={mockOptions}
          placeholder="Pick"
          onSelectOption={handleSelectOption}
          onRemoveTag={jest.fn()}
        />
      );

      await user.click(screen.getByRole("combobox", { name: "Pick" }));
      await user.keyboard("{ArrowDown}{Enter}");
      expect(handleSelectOption).toHaveBeenCalledWith(
        expect.objectContaining({ value: "apple" })
      );
    });

    test("picking a chosen option's row removes the tag", async () => {
      const handleRemoveTag = jest.fn();
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[{ id: "apple", label: "Apple" }]}
          options={mockOptions}
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onRemoveTag={handleRemoveTag}
        />
      );

      await user.click(screen.getByRole("combobox", { name: "Pick" }));
      const row = screen.getByRole("option", { name: /Apple/ });
      expect(row).toHaveAttribute("aria-selected", "true");
      await user.click(row);
      expect(handleRemoveTag).toHaveBeenCalledWith("apple");
    });

    test("a chip's remove button still removes its tag", async () => {
      const handleRemoveTag = jest.fn();
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[{ id: "apple", label: "Apple" }]}
          options={mockOptions}
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onRemoveTag={handleRemoveTag}
        />
      );

      await user.click(screen.getByRole("button", { name: /remove/i }));
      expect(handleRemoveTag).toHaveBeenCalledWith("apple");
    });
  });
});
