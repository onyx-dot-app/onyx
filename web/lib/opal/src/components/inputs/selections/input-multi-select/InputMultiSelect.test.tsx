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
  { value: "apple", label: "Apple" },
  { value: "banana", label: "Banana" },
];

function setupUser() {
  return userEvent.setup({ delay: null });
}

describe("InputMultiSelect", () => {
  describe("Free-form tags", () => {
    test("open mode lists a free-form tag as a selected row", async () => {
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[{ id: "kiwi-1", label: "Kiwi" }]}
          value=""
          onChange={jest.fn()}
          options={mockOptions}
          mode="open"
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onAdd={jest.fn()}
          onRemoveTag={jest.fn()}
        />
      );

      await user.click(screen.getByPlaceholderText("Pick"));

      const row = screen.getByRole("option", { name: /Kiwi/ });
      expect(row).toHaveAttribute("aria-selected", "true");
      // The free-form row precedes the option set.
      expect(screen.getAllByRole("option")[0]).toBe(row);
    });

    test("picking a free-form tag's row removes the tag", async () => {
      const handleRemoveTag = jest.fn();
      const handleAdd = jest.fn();
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[{ id: "kiwi-1", label: "Kiwi" }]}
          value=""
          onChange={jest.fn()}
          options={mockOptions}
          mode="open"
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onAdd={handleAdd}
          onRemoveTag={handleRemoveTag}
        />
      );

      await user.click(screen.getByPlaceholderText("Pick"));
      await user.click(screen.getByRole("option", { name: /Kiwi/ }));

      expect(handleRemoveTag).toHaveBeenCalledWith("kiwi-1");
      expect(handleAdd).not.toHaveBeenCalled();
    });

    test("no option set has no dropdown and Enter commits the text", async () => {
      const handleAdd = jest.fn();
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[{ id: "kiwi-1", label: "Kiwi" }]}
          value=" pear "
          onChange={jest.fn()}
          placeholder="Tag"
          onAdd={handleAdd}
          onRemoveTag={jest.fn()}
        />
      );

      const input = screen.getByPlaceholderText("Tag");
      // A plain textbox, not a combobox: nothing for a dropdown to cover.
      expect(input).not.toHaveAttribute("role");
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();

      await user.click(input);
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("option")).not.toBeInTheDocument();

      await user.keyboard("{Enter}");
      expect(handleAdd).toHaveBeenCalledWith("pear");
    });

    test("closed mode does not list a tag outside the set as a row", async () => {
      const user = setupUser();
      render(
        <InputMultiSelect
          tags={[{ id: "kiwi-1", label: "Kiwi" }]}
          value=""
          onChange={jest.fn()}
          options={mockOptions}
          mode="closed"
          placeholder="Pick"
          onSelectOption={jest.fn()}
          onAdd={jest.fn()}
          onRemoveTag={jest.fn()}
        />
      );

      await user.click(screen.getByPlaceholderText("Pick"));

      expect(
        screen.queryByRole("option", { name: /Kiwi/ })
      ).not.toBeInTheDocument();
    });
  });
});
