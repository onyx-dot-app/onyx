/**
 * Component tests for PasswordInputTypeIn.
 *
 * The field renders a native <input type="password"> (toggled to "text" when
 * revealed) so browsers / password managers recognize it for autofill. These
 * tests lock in that native behavior, the reveal toggle, the constant text
 * size across mask states, and the asterisk overlay's idle, focused, and
 * revealed lifecycle under the default mask.
 */
import React from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { PasswordInputTypeIn } from "@opal/components";

interface ControlledPasswordProps {
  initialValue?: string;
  isNonRevealable?: boolean;
  placeholder?: string;
  mask?: "asterisk" | "native";
}

function ControlledPassword({
  initialValue = "",
  isNonRevealable,
  ...props
}: ControlledPasswordProps) {
  const [value, setValue] = React.useState(initialValue);
  return (
    <PasswordInputTypeIn
      data-testid="pw"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      isNonRevealable={isNonRevealable}
      {...props}
    />
  );
}

const MASKED_SECRET = "✱".repeat(6);

describe("PasswordInputTypeIn", () => {
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
    render(<ControlledPassword initialValue="secret" mask="native" />);

    // The caret and mask dots track the input's font-size, so no state may
    // override it: reveal-toggling must not resize the field's text.
    const wrapper = screen.getByTestId("pw").closest("div.contents");
    expect(wrapper?.className).not.toContain("text-[");

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(wrapper?.className).not.toContain("text-[");
  });

  test("asterisk mask overlays one asterisk per character while idle", () => {
    render(<ControlledPassword initialValue="secret" />);

    expect(screen.getByText(MASKED_SECRET)).toBeInTheDocument();
    // The real value stays natively masked underneath.
    expect(screen.getByTestId("pw")).toHaveAttribute("type", "password");
  });

  test("asterisk mask yields to native dots while focused", async () => {
    const user = setupUser();
    render(<ControlledPassword initialValue="secret" />);

    await user.click(screen.getByTestId("pw"));
    expect(screen.queryByText(MASKED_SECRET)).not.toBeInTheDocument();
  });

  test("asterisk mask clears when revealed", async () => {
    const user = setupUser();
    render(<ControlledPassword initialValue="secret" />);

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(screen.queryByText(MASKED_SECRET)).not.toBeInTheDocument();
    expect(screen.getByTestId("pw")).toHaveAttribute("type", "text");
  });
});
