import { describe, expect, it, jest } from "@jest/globals";
import {
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react-native";
import { Pressable } from "react-native";
import { FormProvider, useForm } from "react-hook-form";

import { Text } from "@/components/ui/text";
import { PasswordInputField, TextInputField } from "@/components/form";
import { useFieldController } from "@/components/form/use-field-controller";

type Values = { email: string };

function SubmitButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="submit"
      onPress={onPress}
    >
      <Text>submit</Text>
    </Pressable>
  );
}

describe("TextInputField", () => {
  it("binds the field value and propagates typing back to the form", () => {
    function Form() {
      const methods = useForm<Values>({ defaultValues: { email: "" } });
      return (
        <FormProvider {...methods}>
          <TextInputField<Values, "email">
            name="email"
            title="Email"
            placeholder="email"
          />
        </FormProvider>
      );
    }
    render(<Form />);

    fireEvent.changeText(screen.getByPlaceholderText("email"), "a@b.com");
    expect(screen.getByPlaceholderText("email").props.value).toBe("a@b.com");
  });

  it("surfaces a validation error into the layout's error slot", async () => {
    function Form() {
      const methods = useForm<Values>({ defaultValues: { email: "" } });
      return (
        <FormProvider {...methods}>
          <TextInputField<Values, "email">
            name="email"
            title="Email"
            placeholder="email"
            rules={{ required: "Email is required" }}
          />
          <SubmitButton onPress={methods.handleSubmit(() => {})} />
        </FormProvider>
      );
    }
    render(<Form />);

    fireEvent.press(screen.getByLabelText("submit"));
    await waitFor(() =>
      expect(screen.getByText("Email is required")).toBeTruthy(),
    );
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("shows a fallback message + alert when the failing rule carries no message", async () => {
    function Form() {
      const methods = useForm<Values>({ defaultValues: { email: "" } });
      return (
        <FormProvider {...methods}>
          <TextInputField<Values, "email">
            name="email"
            title="Email"
            placeholder="email"
            rules={{ required: true }}
          />
          <SubmitButton onPress={methods.handleSubmit(() => {})} />
        </FormProvider>
      );
    }
    render(<Form />);

    fireEvent.press(screen.getByLabelText("submit"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText("Invalid value.")).toBeTruthy();
  });

  it("clears the error row once the field becomes valid", async () => {
    function Form() {
      const methods = useForm<Values>({ defaultValues: { email: "" } });
      return (
        <FormProvider {...methods}>
          <TextInputField<Values, "email">
            name="email"
            title="Email"
            placeholder="email"
            rules={{ required: "Email is required" }}
          />
          <SubmitButton onPress={methods.handleSubmit(() => {})} />
        </FormProvider>
      );
    }
    render(<Form />);

    fireEvent.press(screen.getByLabelText("submit"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());

    fireEvent.changeText(screen.getByPlaceholderText("email"), "a@b.com");
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("renders a disabled field non-editable + a11y-disabled while still submitting its value", async () => {
    const onSubmit = jest.fn();
    function Form() {
      const methods = useForm<Values>({
        defaultValues: { email: "locked@x.com" },
      });
      return (
        <FormProvider {...methods}>
          <TextInputField<Values, "email">
            name="email"
            title="Email"
            placeholder="email"
            disabled
          />
          <SubmitButton onPress={methods.handleSubmit(onSubmit)} />
        </FormProvider>
      );
    }
    render(<Form />);

    const input = screen.getByPlaceholderText("email");
    expect(input.props.editable).toBe(false);
    expect(input.props.accessibilityState?.disabled).toBe(true);

    fireEvent.press(screen.getByLabelText("submit"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toEqual({ email: "locked@x.com" });
  });

  it("works with an explicit `control` prop and no FormProvider", () => {
    function Form() {
      const { control } = useForm<Values>({ defaultValues: { email: "hi" } });
      return (
        <TextInputField<Values, "email">
          name="email"
          title="Email"
          control={control}
          placeholder="email"
        />
      );
    }
    render(<Form />);
    expect(screen.getByPlaceholderText("email").props.value).toBe("hi");
  });
});

describe("PasswordInputField", () => {
  it("binds the value and toggles secureTextEntry via the reveal button", () => {
    type PwValues = { password: string };
    function Form() {
      const methods = useForm<PwValues>({ defaultValues: { password: "" } });
      return (
        <FormProvider {...methods}>
          <PasswordInputField<PwValues, "password">
            name="password"
            title="Password"
            placeholder="pw"
          />
        </FormProvider>
      );
    }
    render(<Form />);

    expect(screen.getByPlaceholderText("pw").props.secureTextEntry).toBe(true);
    fireEvent.changeText(screen.getByPlaceholderText("pw"), "hunter2");
    expect(screen.getByPlaceholderText("pw").props.value).toBe("hunter2");

    fireEvent.press(screen.getByLabelText("Show password"));
    expect(screen.getByPlaceholderText("pw").props.secureTextEntry).toBe(false);
  });
});

describe("useFieldController", () => {
  it("throws when neither a control prop nor a FormProvider is present", () => {
    expect(() => renderHook(() => useFieldController())).toThrow(
      /control.*FormProvider/,
    );
  });
});
