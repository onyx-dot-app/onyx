import { router } from "expo-router";
import { ActivityIndicator } from "react-native";

import { useAuthConfig } from "@/api/auth/useAuthConfig";
import { visibleProviders } from "@/api/auth/providers";
import { AuthMethods } from "@/components/auth/AuthMethods";
import { AuthScreenShell } from "@/components/auth/AuthScreenShell";
import { AuthSwitchLink } from "@/components/auth/AuthSwitchLink";
import { InputErrorText } from "@/components/form";
import { Text } from "@/components/ui/text";

export default function SignupScreen() {
  const authConfig = useAuthConfig();
  const providers = visibleProviders(authConfig.data);
  const passwordMinLength = authConfig.data?.password_min_length ?? 8;

  return (
    <AuthScreenShell
      title="Create account"
      subtitle="Get started with Onyx"
      footer={
        <AuthSwitchLink
          prompt="Already have an account?"
          actionLabel="Sign In"
          onPress={() => router.replace("/(auth)/login")}
        />
      }
    >
      {authConfig.isPending ? (
        <ActivityIndicator accessibilityLabel="Loading sign-up options" />
      ) : authConfig.isError ? (
        <InputErrorText>
          Couldn&apos;t load sign-up options for this instance.
        </InputErrorText>
      ) : providers.length === 0 ? (
        <Text font="main-content-body" color="text-03">
          Sign-up for this instance isn&apos;t supported in the mobile app yet.
        </Text>
      ) : (
        <AuthMethods
          providers={providers}
          isSignup
          passwordMinLength={passwordMinLength}
        />
      )}
    </AuthScreenShell>
  );
}
