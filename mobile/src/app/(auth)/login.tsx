// Login screen — mobile port of web's login UI (web/src/app/auth/login/). Email/password
// via the RHF form atoms; V1 is password-only (provider registry adds Google/SSO later).
import { router } from "expo-router";
import { useEffect } from "react";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { ActivityIndicator, View } from "react-native";

import { useAuthConfig } from "@/api/auth/useAuthConfig";
import { useEmailLogin } from "@/api/auth/useEmailLogin";
import { visibleProviders } from "@/api/auth/providers";
import { getErrorMessage, isApiError } from "@/api/errors";
import { AuthScreenShell } from "@/components/auth/AuthScreenShell";
import {
  InputErrorText,
  PasswordInputField,
  TextInputField,
} from "@/components/form";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import SvgArrowRightCircle from "@/icons/arrow-right-circle";

interface LoginValues {
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

function EmailPasswordForm() {
  const form = useForm<LoginValues>({
    defaultValues: { email: "", password: "" },
    mode: "onTouched",
  });
  const loginMutation = useEmailLogin();

  // Clear the API error on edit. `useWatch` not `form.watch` (React-Compiler safe).
  const [email, password] = useWatch({
    control: form.control,
    name: ["email", "password"],
  });
  useEffect(() => {
    if (loginMutation.isError) loginMutation.reset();
    // loginMutation's identity changes every render, so it's excluded from deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email, password]);

  const onSubmit = form.handleSubmit((values) => {
    loginMutation.mutate(
      { email: values.email.trim().toLowerCase(), password: values.password },
      { onSuccess: () => router.replace("/") },
    );
  });

  return (
    <FormProvider {...form}>
      <TextInputField<LoginValues, "email">
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
        <PasswordInputField<LoginValues, "password">
          name="password"
          title="Password"
          placeholder="●●●●●●●●●●●●●●"
          rules={{ required: "Enter your password." }}
          autoComplete="current-password"
          textContentType="password"
          returnKeyType="go"
          onSubmitEditing={() => onSubmit()}
        />
      </View>
      {loginMutation.isError ? (
        <View className="mt-12">
          <InputErrorText>
            {loginErrorMessage(loginMutation.error)}
          </InputErrorText>
        </View>
      ) : null}
      <View className="mt-16">
        <Button
          width="full"
          rightIcon={SvgArrowRightCircle}
          disabled={loginMutation.isPending}
          onPress={onSubmit}
        >
          {loginMutation.isPending ? "Signing in…" : "Sign In"}
        </Button>
      </View>
    </FormProvider>
  );
}

export default function LoginScreen() {
  const authConfig = useAuthConfig();
  const providers = visibleProviders(authConfig.data);
  const hasPassword = providers.some(
    (provider) => provider.kind === "password",
  );

  return (
    <AuthScreenShell
      title="Welcome to Onyx"
      subtitle="Your open source AI platform for work"
      footer={
        <Button
          variant="action"
          prominence="tertiary"
          size="md"
          onPress={() => router.replace("/(auth)/connect")}
        >
          Connect to a different instance
        </Button>
      }
    >
      {authConfig.isPending ? (
        <ActivityIndicator accessibilityLabel="Loading sign-in options" />
      ) : authConfig.isError ? (
        <InputErrorText>
          Couldn&apos;t load sign-in options for this instance.
        </InputErrorText>
      ) : hasPassword ? (
        <EmailPasswordForm />
      ) : (
        <Text font="main-content-body" color="text-03">
          Sign-in for this instance isn&apos;t supported in the mobile app yet.
        </Text>
      )}
    </AuthScreenShell>
  );
}
