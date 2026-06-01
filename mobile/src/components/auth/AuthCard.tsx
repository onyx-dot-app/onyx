import type { ReactNode } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, View } from "react-native";

import { Text } from "@/components/opal";
import { OnyxLogo } from "@/components/ui/logos";
import { useThemeColors } from "@/theme/ThemeProvider";

interface AuthCardProps {
  // Card header copy, beneath the Onyx logo.
  title: string;
  subtitle: string;
  // Card body (Google button, divider, form, etc.).
  children: ReactNode;
  // Optional navigation row rendered below the card.
  footer?: ReactNode;
}

// Shared scaffold for the login and register screens: a keyboard-avoiding,
// centered scroll view wrapping an Onyx-logo-topped card, with an optional
// footer row beneath. Native mirror of web `AuthFlowContainer`.
export function AuthCard({ title, subtitle, children, footer }: AuthCardProps) {
  const colors = useThemeColors();

  return (
    <KeyboardAvoidingView
      className="flex-1 bg-background-neutral-00"
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        className="flex-1"
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: "center",
          alignItems: "center",
          padding: 16,
        }}
        keyboardShouldPersistTaps="handled"
      >
        <View className="w-full max-w-md gap-6">
          <View className="gap-6 rounded-[16px] border border-border-01 bg-background-tint-00 p-6">
            <View className="gap-3">
              <OnyxLogo size={44} color={colors["theme-primary-05"]} />
              <View className="gap-1">
                <Text font="heading-h2" color="text-05">
                  {title}
                </Text>
                <Text font="main-ui-muted" color="text-03">
                  {subtitle}
                </Text>
              </View>
            </View>

            {children}
          </View>

          {footer}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
