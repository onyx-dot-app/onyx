import { View } from "react-native";

import type { ProviderDescriptor } from "@/api/auth/providers";
import { EmailPasswordForm } from "@/components/auth/EmailPasswordForm";
import { ProviderSsoButton } from "@/components/auth/ProviderSsoButton";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";

interface AuthMethodsProps {
  providers: ProviderDescriptor[];
  isSignup?: boolean;
  passwordMinLength?: number;
}

export function AuthMethods({
  providers,
  isSignup = false,
  passwordMinLength,
}: AuthMethodsProps) {
  const hasPassword = providers.some(
    (provider) => provider.kind === "password",
  );
  const browserProviders = providers.filter(
    (provider) => provider.kind === "browser",
  );

  return (
    <>
      {hasPassword ? (
        <EmailPasswordForm
          isSignup={isSignup}
          passwordMinLength={passwordMinLength}
        />
      ) : null}
      {hasPassword && browserProviders.length > 0 ? (
        <View className="my-16 flex-row items-center">
          <View className="h-px flex-1 bg-border-01" />
          <Text font="main-ui-muted" color="text-03" className="mx-8">
            or
          </Text>
          <View className="h-px flex-1 bg-border-01" />
        </View>
      ) : null}
      {browserProviders.map((provider, index) => (
        <View key={provider.id} className={cn(index > 0 && "mt-12")}>
          <ProviderSsoButton provider={provider} />
        </View>
      ))}
    </>
  );
}
