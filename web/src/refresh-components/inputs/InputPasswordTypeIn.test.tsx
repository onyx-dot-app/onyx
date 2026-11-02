/**
 * Component tests for InputPasswordTypeIn.
 *
 * The field renders a native <input type="password"> (toggled to "text" when
 * revealed) so browsers / password managers recognize it for autofill. These
 * tests lock in that native behavior, the reveal toggle, the constant text
 * size across mask states, and the existing-value tag.
 */
import React from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { InputPasswordTypeIn } from "@opal/components";

interface ControlledPasswordProps {
  initialValue?: string;
  isNonRevealable?: boolean;
  existingValue?: string;
  placeholder?: string;
}

function ControlledPassword({
  initialValue = "",
  isNonRevealable,
  ...props
}: ControlledPasswordProps) {
  const [value, setValue] = React.useState(initialValue);
  return (
    <InputPasswordTypeIn
      data-testid="pw"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      isNonRevealable={isNonRevealable}
      {...props}
    />
  );
}

describe("InputPasswordTypeIn", () => {
  test("renders a native password input by default", () => {
    render(<ControlledPassword initialValue="secret" />);
    expect(screen.getByTestId("pw")).toHaveAttribute("type", "password");
  });

  test("toggles between hidden and revealed", async () => {
    const user = setupUser();
    render(<ControlledPassword initialValue="secret" />);

    const input = screen.getByTestId("pw");
    expect(input).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(input).toHaveAttribute("type", "text");

    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input).toHaveAttribute("type", "password");
  });

  test("passes typed input through to onChange", async () => {
    const user = setupUser();
    render(<ControlledPassword />);

    const input = screen.getByTestId("pw");
    await user.type(input, "hunter2");
    expect(input).toHaveValue("hunter2");
  });

  test("stays masked and cannot be revealed when isNonRevealable", async () => {
    const user = setupUser();
    render(<ControlledPassword initialValue="secret" isNonRevealable />);

    const input = screen.getByTestId("pw");
    const toggle = screen.getByRole("button", {
      name: "Value cannot be revealed",
    });

    await user.click(toggle);
    expect(input).toHaveAttribute("type", "password");
  });

  test("keeps the text size constant between hidden and revealed", async () => {
    const user = setupUser();
    render(<ControlledPassword initialValue="secret" />);

    // The caret and mask dots track the input's font-size, so no state may
    // override it: reveal-toggling must not resize the field's text.
    const wrapper = screen.getByTestId("pw").closest("div.contents");
    expect(wrapper?.className).not.toContain("text-[");

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(wrapper?.className).not.toContain("text-[");
  });

  test("never draws an asterisk overlay", () => {
    render(<ControlledPassword initialValue="secret" />);

    expect(screen.queryByText(/✱/)).not.toBeInTheDocument();
    expect(screen.getByTestId("pw")).toHaveAttribute("type", "password");
  });

  test("Escape on the reveal toggle returns focus to the field", async () => {
    const user = setupUser();
    render(<ControlledPassword initialValue="secret" />);
    const input = screen.getByTestId("pw");

    await user.click(input);
    await user.tab();
    expect(screen.getByRole("button", { name: "Show password" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(input).toHaveFocus();
  });

  describe("existingValue", () => {
    const EXISTING = "sk-abcd...wxyz";

    function renderExisting() {
      render(
        <ControlledPassword initialValue={EXISTING} existingValue={EXISTING} />
      );
      return screen.getByTestId("pw");
    }

    test("backspace clears the whole existing value", async () => {
      const user = setupUser();
      const input = renderExisting();

      await user.type(input, "{Backspace}");
      expect(input).toHaveValue("");
    });

    test("typing replaces the existing value with the keystroke", async () => {
      const user = setupUser();
      const input = renderExisting();

      await user.type(input, "n");
      expect(input).toHaveValue("n");
      await user.type(input, "ew");
      expect(input).toHaveValue("new");
    });

    test("pasting replaces the existing value", async () => {
      const user = setupUser();
      const input = renderExisting();

      await user.click(input);
      await user.paste("pasted-key");
      expect(input).toHaveValue("pasted-key");
    });

    test("shows the existing value as a tag that cannot be revealed", () => {
      const input = renderExisting();

      expect(screen.getByText(EXISTING)).toBeInTheDocument();
      expect(input).toHaveValue("");
      expect(input).toHaveAttribute("type", "password");
      expect(
        screen.getByRole("button", { name: "Value cannot be revealed" })
      ).toBeDisabled();
      expect(screen.queryByText(/✱/)).toBeNull();
    });

    test("delete clears the whole existing value", async () => {
      const user = setupUser();
      const input = renderExisting();

      await user.type(input, "{Delete}");
      expect(input).toHaveValue("");
      expect(screen.queryByText(EXISTING)).toBeNull();
    });

    test("a read-only field keeps the existing value on Backspace", async () => {
      const user = setupUser();
      render(
        <InputPasswordTypeIn
          data-testid="pw"
          value={EXISTING}
          existingValue={EXISTING}
          onChange={() => {
            throw new Error("onChange must not run");
          }}
          readOnly
        />
      );

      await user.type(screen.getByTestId("pw"), "{Backspace}");
      expect(screen.getByText(EXISTING)).toBeInTheDocument();
    });

    test("the caller's onKeyDown can cancel the deletion", async () => {
      const user = setupUser();
      const onChange = jest.fn();
      render(
        <InputPasswordTypeIn
          data-testid="pw"
          value={EXISTING}
          existingValue={EXISTING}
          onChange={onChange}
          onKeyDown={(event) => event.preventDefault()}
        />
      );

      await user.type(screen.getByTestId("pw"), "{Backspace}");
      expect(onChange).not.toHaveBeenCalled();
    });

    test("an unchanged existing value does not fail a native required check", () => {
      render(
        <InputPasswordTypeIn
          data-testid="pw"
          value={EXISTING}
          existingValue={EXISTING}
          onChange={() => {}}
          required
        />
      );

      expect(screen.getByTestId("pw")).not.toBeRequired();
    });

    test("a new value can be revealed and edited normally", async () => {
      const user = setupUser();
      const input = renderExisting();

      await user.type(input, "{Backspace}abc{Backspace}");
      expect(input).toHaveValue("ab");
      await user.click(screen.getByRole("button", { name: "Show password" }));
      expect(input).toHaveAttribute("type", "text");
    });
  });
});
