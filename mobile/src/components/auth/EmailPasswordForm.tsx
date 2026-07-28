import { router } from "expo-router";
import { useEffect } from "react";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { View } from "react-native";

import { PostRegisterLoginError } from "@/api/auth/sessionManager";
import { useEmailLogin } from "@/api/auth/useEmailLogin";
import { useEmailSignup } from "@/api/auth/useEmailSignup";
import { getErrorMessage, isApiError } from "@/api/errors";
import {
  InputErrorText,
  PasswordInputField,
  TextInputField,
} from "@/components/form";
import { Button } from "@/components/ui/button";
import SvgArrowRightCircle from "@/icons/arrow-right-circle";

interface EmailPasswordValues {
  email: string;
  password: string;
}

// Permissive client-side email shape; the backend is the real validator.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Enumeration-safe + handles fastapi-users' 400 for bad creds (not just 401).
function loginErrorMessage(error: unknown): string {
  if (isApiError(error) && (error.status === 400 || error.status === 401)) {
    return "Invalid email or password.";
  }
  return getErrorMessage(error, "Couldn't sign in. Please try again.");
}

function signupErrorMessage(error: unknown): string {
  // Account created; only auto-login failed — point at sign-in, not retry-signup.
  if (error instanceof PostRegisterLoginError) {
    return "Account created. Please sign in.";
  }
  if (isApiError(error)) {
    if (error.detail === "REGISTER_USER_ALREADY_EXISTS") {
      return "An account already exists with this email.";
    }
    if (error.status === 429) {
      return "Too many requests. Please try again later.";
    }
    // Weak-password rejection is `{ detail: { reason } }`; apiFetch can't flatten an object detail, so read the raw body.
    const body = error.body as { detail?: { reason?: string } } | undefined;
    const reason = body?.detail?.reason;
    if (typeof reason === "string" && reason) return reason;
  }
  return getErrorMessage(
    error,
    "Couldn't create your account. Please try again.",
  );
}

interface EmailPasswordFormProps {
  isSignup?: boolean;
  passwordMinLength?: number;
}

export function EmailPasswordForm({
  isSignup = false,
  passwordMinLength = 8,
}: EmailPasswordFormProps) {
  const form = useForm<EmailPasswordValues>({
    defaultValues: { email: "", password: "" },
    mode: "onTouched",
  });
  const loginMutation = useEmailLogin();
  const signupMutation = useEmailSignup();
  const mutation = isSignup ? signupMutation : loginMutation;

  // Clear the API error on edit. `useWatch` not `form.watch` (React-Compiler safe).
  const [email, password] = useWatch({
    control: form.control,
    name: ["email", "password"],
  });
  useEffect(() => {
    if (mutation.isError) mutation.reset();
    // `mutation` excluded from deps: it changes when `isError` flips, so including it would reset the error the instant it's set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email, password]);

  const onSubmit = form.handleSubmit((values) => {
    mutation.mutate(
      { email: values.email.trim().toLowerCase(), password: values.password },
      { onSuccess: () => router.replace("/") },
    );
  });

  const errorMessage = isSignup ? signupErrorMessage : loginErrorMessage;

  // iOS's "Automatic Strong Password" overlay (triggered by the `newPassword`
  // content type) can't be dismissed against the simulator's empty Keychain, so
  // it blocks typing during local testing. Disable AutoFill on the signup field
  // in dev builds only — release builds keep the proper password-manager hints.
  const suppressAutoFill = isSignup && __DEV__;

  return (
    <FormProvider {...form}>
      <TextInputField<EmailPasswordValues, "email">
        name="email"
        title="Email Address"
        placeholder="email@yourcompany.com"
        rules={{
          required: "Enter your email.",
          pattern: {
            value: EMAIL_PATTERN,
            message: "Enter a valid email address.",
          },
        }}
        keyboardType="email-address"
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="email"
        textContentType="username"
        returnKeyType="next"
      />
      <View className="mt-12">
        <PasswordInputField<EmailPasswordValues, "password">
          name="password"
          title="Password"
          placeholder="●●●●●●●●●●●●●●"
          subDescription={
            isSignup
              ? `Must be at least ${passwordMinLength} characters.`
              : undefined
          }
          rules={{
            required: "Enter your password.",
            ...(isSignup && {
              minLength: {
                value: passwordMinLength,
                message: `Must be at least ${passwordMinLength} characters.`,
              },
            }),
          }}
          autoComplete={
            suppressAutoFill
              ? "off"
              : isSignup
                ? "new-password"
                : "current-password"
          }
          textContentType={
            suppressAutoFill ? "none" : isSignup ? "newPassword" : "password"
          }
          returnKeyType="go"
          onSubmitEditing={() => onSubmit()}
        />
      </View>
      {mutation.isError ? (
        <View className="mt-12">
          <InputErrorText>{errorMessage(mutation.error)}</InputErrorText>
        </View>
      ) : null}
      <View className="mt-16">
        <Button
          width="full"
          rightIcon={SvgArrowRightCircle}
          loading={mutation.isPending}
          onPress={onSubmit}
        >
          {isSignup
            ? mutation.isPending
              ? "Creating account…"
              : "Create Account"
            : mutation.isPending
              ? "Signing in…"
              : "Sign In"}
        </Button>
      </View>
    </FormProvider>
  );
}
