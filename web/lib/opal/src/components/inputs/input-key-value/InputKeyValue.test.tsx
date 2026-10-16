import { useState } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { InputKeyValue, type KeyValue } from "@opal/components";

describe("InputKeyValue", () => {
  it("keeps keys and values as plain text by default", () => {
    render(
      <InputKeyValue
        items={[{ key: "Authorization", value: "Bearer {api_key}" }]}
        onChange={jest.fn()}
      />
    );

    expect(screen.getByRole("textbox", { name: "Key 1" })).toHaveValue(
      "Authorization"
    );
    expect(screen.getByRole("textbox", { name: "Value 1" })).toHaveValue(
      "Bearer {api_key}"
    );
    expect(screen.getByLabelText("Value 1")).toHaveAttribute("type", "text");
    expect(
      screen.queryByRole("button", { name: "Show password" })
    ).not.toBeInTheDocument();
  });

  it("masks password values until the user reveals them", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(
      <InputKeyValue
        valueType="password"
        items={[{ key: "api_key", value: "sk-original-secret" }]}
        onChange={onChange}
      />
    );

    const value = screen.getByLabelText("Value 1");
    expect(screen.getByRole("textbox", { name: "Key 1" })).toHaveValue(
      "api_key"
    );
    expect(value).toHaveAttribute("type", "password");
    expect(value).toHaveAttribute("autocomplete", "new-password");
    expect(value).toHaveAttribute("data-ph-no-capture");
    expect(value).toHaveValue("sk-original-secret");

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(value).toHaveAttribute("type", "text");
    expect(value).toHaveValue("sk-original-secret");

    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(value).toHaveAttribute("type", "password");
    expect(value).toHaveValue("sk-original-secret");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps password row editing, validation, add, and remove behavior", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    const onValidationError = jest.fn();

    function Harness() {
      const [items, setItems] = useState<KeyValue[]>([
        { key: "api_key", value: "sk-original-secret" },
      ]);
      return (
        <InputKeyValue
          valueType="password"
          items={items}
          onChange={(next) => {
            setItems(next);
            onChange(next);
          }}
          onValidationError={onValidationError}
        />
      );
    }

    render(<Harness />);

    await user.clear(screen.getByLabelText("Value 1"));
    await user.type(screen.getByLabelText("Value 1"), "sk-replacement");
    expect(onChange).toHaveBeenLastCalledWith([
      { key: "api_key", value: "sk-replacement" },
    ]);

    await user.click(
      screen.getByRole("button", { name: "Add Key and Value pair" })
    );
    await user.type(screen.getByLabelText("Value 2"), "second-secret");
    expect(screen.getByLabelText("Key 2")).toHaveAttribute(
      "aria-invalid",
      "true"
    );
    expect(onValidationError).toHaveBeenLastCalledWith("1 empty key found");

    await user.type(screen.getByLabelText("Key 2"), "api_key");
    expect(screen.getAllByText("Duplicate key")).toHaveLength(2);
    expect(onValidationError).toHaveBeenLastCalledWith(
      "2 duplicate keys found"
    );

    await user.click(
      screen.getByRole("button", { name: "Remove key-value pair 2" })
    );
    expect(onChange).toHaveBeenLastCalledWith([
      { key: "api_key", value: "sk-replacement" },
    ]);
    expect(onValidationError).toHaveBeenLastCalledWith(null);
    expect(screen.getByLabelText("Value 1")).toHaveAttribute(
      "type",
      "password"
    );
  });

  it("keeps the next credential hidden after removing a revealed row", async () => {
    const user = setupUser();

    function Harness() {
      const [items, setItems] = useState<KeyValue[]>([
        { key: "api_key", value: "first-secret" },
        { key: "client_secret", value: "second-secret" },
      ]);
      return (
        <InputKeyValue valueType="password" items={items} onChange={setItems} />
      );
    }

    render(<Harness />);
    await user.click(screen.getByLabelText("Value 1"));
    await user.tab();
    await user.keyboard("{Enter}");
    expect(screen.getByLabelText("Value 1")).toHaveAttribute("type", "text");

    await user.click(
      screen.getByRole("button", { name: "Remove key-value pair 1" })
    );

    expect(screen.getByLabelText("Key 1")).toHaveValue("client_secret");
    expect(screen.getByLabelText("Value 1")).toHaveValue("second-secret");
    expect(screen.getByLabelText("Value 1")).toHaveAttribute(
      "type",
      "password"
    );
  });
});
