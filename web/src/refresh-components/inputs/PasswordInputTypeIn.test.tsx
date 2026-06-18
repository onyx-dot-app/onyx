/**
 * Component tests for PasswordInputTypeIn.
 *
 * The field renders a native <input type="password"> (toggled to "text" when
 * revealed) so browsers / password managers recognize it for autofill. These
 * tests lock in that native behavior and the reveal toggle.
 */
import React from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import PasswordInputTypeIn from "./PasswordInputTypeIn";

interface ControlledPasswordProps {
  initialValue?: string;
  isNonRevealable?: boolean;
  placeholder?: string;
  shrinkPlaceholder?: boolean;
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

  test("shrinks the masked dots while hidden but not when revealed", async () => {
    const user = setupUser();
    render(<ControlledPassword initialValue="secret" />);

    // Applied whenever hidden (even before typing) so the size is constant
    // across keystrokes.
    const wrapper = screen.getByTestId("pw").closest("div.contents");
    expect(wrapper?.className).toContain("[&_input]:!text-[0.6rem]");

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(wrapper?.className).not.toContain("[&_input]:!text-[0.6rem]");
  });

  test("shrinks the placeholder when shrinkPlaceholder is set", () => {
    render(<ControlledPassword placeholder="●●●●●●●●" shrinkPlaceholder />);

    const wrapper = screen.getByTestId("pw").closest("div.contents");
    expect(wrapper?.className).toContain(
      "[&_input::placeholder]:!text-[0.6rem]"
    );
  });

  test("leaves a custom text placeholder at full size by default", () => {
    render(<ControlledPassword placeholder="Your long-term API key" />);

    // The input value still shrinks while hidden, but the custom text
    // placeholder must stay legible at its normal Opal size.
    const wrapper = screen.getByTestId("pw").closest("div.contents");
    expect(wrapper?.className).toContain("[&_input]:!text-[0.6rem]");
    expect(wrapper?.className).not.toContain(
      "[&_input::placeholder]:!text-[0.6rem]"
    );
  });
});
