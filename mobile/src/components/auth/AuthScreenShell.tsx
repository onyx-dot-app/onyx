// Shared full-screen chrome for the connect + login screens (mobile adaptation of web's
// AuthFlowContainer + LoginText): Onyx logo, welcome heading, then the caller's form.
import type { ReactNode } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import SvgOnyxLogo from "@/icons/onyx-logo";

interface AuthScreenShellProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}

export function AuthScreenShell({
  title,
  subtitle,
  children,
  footer,
}: AuthScreenShellProps) {
  return (
    <SafeAreaView className="flex-1 bg-background-neutral-00">
      <KeyboardAvoidingView
        className="flex-1"
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerClassName="grow justify-center px-24 py-40"
          keyboardShouldPersistTaps="handled"
        >
          <Icon as={SvgOnyxLogo} size={44} className="text-theme-primary-05" />
          <View className="mt-12">
            <Text font="heading-h2" color="text-05">
              {title}
            </Text>
            {subtitle ? (
              <Text font="main-ui-muted" color="text-03" className="mt-4">
                {subtitle}
              </Text>
            ) : null}
          </View>
          <View className="mt-24 w-full">{children}</View>
          {footer ? (
            <View className="mt-24 w-full items-center">{footer}</View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
