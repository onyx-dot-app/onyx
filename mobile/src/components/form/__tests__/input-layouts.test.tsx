import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";
import { createRef } from "react";
import { type TextInput as RNTextInputType } from "react-native";

import { Text } from "@/components/ui/text";
import {
  InputErrorText,
  PasswordTextInput,
  TextInput,
  Vertical,
} from "@/components/form";

describe("Vertical", () => {
  it("renders the title + description and shows the error row only when error is set", () => {
    const { rerender } = render(
      <Vertical title="Email" description="Your work email">
        <Text>input</Text>
      </Vertical>,
    );
    expect(screen.getByText("Email")).toBeTruthy();
    expect(screen.getByText("Your work email")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();

    rerender(
      <Vertical title="Email" error="Enter a valid email">
        <Text>input</Text>
      </Vertical>,
    );
    expect(screen.getByText("Enter a valid email")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("renders subDescription below the input", () => {
    render(
      <Vertical title="Email" subDescription="We never share it">
        <Text>input</Text>
      </Vertical>,
    );
    expect(screen.getByText("We never share it")).toBeTruthy();
  });
});

describe("InputErrorText", () => {
  it("renders nothing when empty", () => {
    render(<InputErrorText>{undefined}</InputErrorText>);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders the message with an alert role", () => {
    render(<InputErrorText type="warning">Careful now</InputErrorText>);
    expect(screen.getByText("Careful now")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});

describe("TextInput", () => {
  it("is not editable for the disabled variant", () => {
    render(
      <TextInput
        variant="disabled"
        value="x"
        onChangeText={() => {}}
        placeholder="ph"
      />,
    );
    expect(screen.getByPlaceholderText("ph").props.editable).toBe(false);
  });

  it("stays editable for the internal variant", () => {
    render(
      <TextInput
        variant="internal"
        value="x"
        onChangeText={() => {}}
        placeholder="ph"
      />,
    );
    expect(screen.getByPlaceholderText("ph").props.editable).toBe(true);
  });

  it("renders prefix text before the input", () => {
    render(
      <TextInput
        prefixText="https://"
        value=""
        onChangeText={() => {}}
        placeholder="ph"
      />,
    );
    expect(screen.getByText("https://")).toBeTruthy();
  });

  it("clears the field when pressed, and the slot stays mounted but inert when empty", () => {
    const onChangeText = jest.fn();
    const { rerender } = render(
      <TextInput
        clearButton
        value="hello"
        onChangeText={onChangeText}
        placeholder="ph"
      />,
    );
    fireEvent.press(screen.getByLabelText("Clear"));
    expect(onChangeText).toHaveBeenCalledWith("");

    onChangeText.mockClear();
    rerender(
      <TextInput
        clearButton
        value=""
        onChangeText={onChangeText}
        placeholder="ph"
      />,
    );
    fireEvent.press(screen.getByLabelText("Clear"));
    expect(onChangeText).not.toHaveBeenCalled();
  });

  it("forwards its ref to the underlying input", () => {
    const ref = createRef<RNTextInputType>();
    render(
      <TextInput ref={ref} value="" onChangeText={() => {}} placeholder="ph" />,
    );
    expect(ref.current).toBeTruthy();
  });

  it("focuses the input when the shell is tapped, but not when disabled", () => {
    const ref = createRef<RNTextInputType>();
    const { rerender } = render(
      <TextInput ref={ref} value="" onChangeText={() => {}} placeholder="ph" />,
    );
    const focusSpy = jest.spyOn(ref.current as RNTextInputType, "focus");
    fireEvent.press(screen.getByPlaceholderText("ph"));
    expect(focusSpy).toHaveBeenCalled();

    focusSpy.mockClear();
    rerender(
      <TextInput
        ref={ref}
        variant="disabled"
        value="x"
        onChangeText={() => {}}
        placeholder="ph"
      />,
    );
    fireEvent.press(screen.getByPlaceholderText("ph"));
    expect(focusSpy).not.toHaveBeenCalled();
  });
});

describe("PasswordTextInput", () => {
  it("toggles secureTextEntry when the reveal button is pressed", () => {
    render(
      <PasswordTextInput
        value="secret"
        onChangeText={() => {}}
        placeholder="pw"
      />,
    );
    expect(screen.getByPlaceholderText("pw").props.secureTextEntry).toBe(true);

    fireEvent.press(screen.getByLabelText("Show password"));
    expect(screen.getByPlaceholderText("pw").props.secureTextEntry).toBe(false);

    fireEvent.press(screen.getByLabelText("Hide password"));
    expect(screen.getByPlaceholderText("pw").props.secureTextEntry).toBe(true);
  });

  it("hides the reveal toggle until the field has a value or focus", () => {
    render(
      <PasswordTextInput value="" onChangeText={() => {}} placeholder="pw" />,
    );
    expect(screen.queryByLabelText("Show password")).toBeNull();

    fireEvent(screen.getByPlaceholderText("pw"), "focus");
    expect(screen.getByLabelText("Show password")).toBeTruthy();
  });

  it("disables the reveal toggle for a non-revealable backend placeholder", () => {
    render(
      <PasswordTextInput
        value={"•".repeat(8)}
        onChangeText={() => {}}
        placeholder="pw"
      />,
    );
    const toggle = screen.getByLabelText("Value cannot be revealed");
    expect(toggle.props.accessibilityState?.disabled).toBe(true);
  });

  it("defaults autoComplete to new-password", () => {
    render(
      <PasswordTextInput value="" onChangeText={() => {}} placeholder="pw" />,
    );
    expect(screen.getByPlaceholderText("pw").props.autoComplete).toBe(
      "new-password",
    );
  });
});
