import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { InputTypeInTag } from "./components";

function setupUser() {
  return userEvent.setup({ delay: null });
}

describe("InputTypeInTag", () => {
  test("is a plain textbox with no dropdown", async () => {
    const user = setupUser();
    render(
      <InputTypeInTag
        tags={[{ id: "kiwi-1", label: "Kiwi" }]}
        value=""
        onChange={jest.fn()}
        placeholder="Tag"
        onAdd={jest.fn()}
        onRemoveTag={jest.fn()}
      />
    );

    const input = screen.getByPlaceholderText("Tag");
    expect(input).not.toHaveAttribute("role");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();

    await user.click(input);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  test("Enter commits the trimmed text through onAdd", async () => {
    const handleAdd = jest.fn();
    const user = setupUser();
    render(
      <InputTypeInTag
        tags={[]}
        value=" pear "
        onChange={jest.fn()}
        placeholder="Tag"
        onAdd={handleAdd}
        onRemoveTag={jest.fn()}
      />
    );

    await user.click(screen.getByPlaceholderText("Tag"));
    await user.keyboard("{Enter}");
    expect(handleAdd).toHaveBeenCalledWith("pear");
  });

  test("Enter on empty text is a no-op", async () => {
    const handleAdd = jest.fn();
    const user = setupUser();
    render(
      <InputTypeInTag
        tags={[]}
        value="   "
        onChange={jest.fn()}
        placeholder="Tag"
        onAdd={handleAdd}
        onRemoveTag={jest.fn()}
      />
    );

    await user.click(screen.getByPlaceholderText("Tag"));
    await user.keyboard("{Enter}");
    expect(handleAdd).not.toHaveBeenCalled();
  });

  test("Backspace on an empty input arms the last tag, and again removes it", async () => {
    const handleRemoveTag = jest.fn();
    const user = setupUser();
    render(
      <InputTypeInTag
        tags={[
          { id: "kiwi-1", label: "Kiwi" },
          { id: "pear-1", label: "Pear" },
        ]}
        value=""
        onChange={jest.fn()}
        placeholder="Tag"
        onAdd={jest.fn()}
        onRemoveTag={handleRemoveTag}
      />
    );

    await user.click(screen.getByPlaceholderText("Tag"));
    await user.keyboard("{Backspace}");
    expect(screen.getByRole("button", { name: /Pear/ })).toHaveFocus();

    await user.keyboard("{Backspace}");
    expect(handleRemoveTag).toHaveBeenCalledWith("pear-1");
  });
});
