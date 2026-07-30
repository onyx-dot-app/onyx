import { router } from "expo-router";
import { ActivityIndicator, View } from "react-native";

import { useAuthConfig } from "@/api/auth/useAuthConfig";
import { visibleProviders } from "@/api/auth/providers";
import { AuthMethods } from "@/components/auth/AuthMethods";
import { AuthScreenShell } from "@/components/auth/AuthScreenShell";
import { AuthSwitchLink } from "@/components/auth/AuthSwitchLink";
import { InputErrorText } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";

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
        <>
          {hasPassword ? (
            <AuthSwitchLink
              prompt="New to Onyx?"
              actionLabel="Create an Account"
              onPress={() => router.replace("/(auth)/signup")}
            />
          ) : null}
          <View
            className={cn(
              "w-full flex-row justify-center",
              hasPassword && "mt-12",
            )}
          >
            <Button
              variant="action"
              prominence="tertiary"
              size="md"
              onPress={() => router.replace("/(auth)/connect")}
            >
              Connect to a different instance
            </Button>
          </View>
        </>
      }
    >
      {authConfig.isPending ? (
        <ActivityIndicator accessibilityLabel="Loading sign-in options" />
      ) : authConfig.isError ? (
        <InputErrorText>
          Couldn&apos;t load sign-in options for this instance.
        </InputErrorText>
      ) : providers.length === 0 ? (
        <Text font="main-content-body" color="text-03">
          Sign-in for this instance isn&apos;t supported in the mobile app yet.
        </Text>
      ) : (
        <AuthMethods providers={providers} />
      )}
    </AuthScreenShell>
  );
}
