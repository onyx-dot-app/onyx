import { describe, expect, it } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";
import { Text as RNText } from "react-native";

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
        <RNText>input</RNText>
      </Vertical>,
    );
    expect(screen.getByText("Email")).toBeTruthy();
    expect(screen.getByText("Your work email")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();

    rerender(
      <Vertical title="Email" error="Enter a valid email">
        <RNText>input</RNText>
      </Vertical>,
    );
    expect(screen.getByText("Enter a valid email")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("renders subDescription below the input", () => {
    render(
      <Vertical title="Email" subDescription="We never share it">
        <RNText>input</RNText>
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
});
