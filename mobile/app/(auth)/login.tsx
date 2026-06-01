import { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { router } from "expo-router";

import { useAuth, SignInCancelledError } from "@/auth";
import { Text, Button } from "@/components/opal";
import { GoogleLogo, OnyxLogo } from "@/components/ui/logos";
import { useThemeColors } from "@/theme/ThemeProvider";

// Sign-in screen. Mirrors the web auth layout (web/src/components/auth/
// AuthFlowContainer + app/auth/login): an Onyx-logo-topped card with a
// "Continue with Google" button, an "or" divider, and the email/password form.
// Password creds post to the backend's mobile Bearer login route, which returns
// a JWT the AuthProvider stores; on success status flips to signedIn and
// app/index.tsx routes into (app). "Create an Account" pushes the registration
// screen.
export default function Login() {
  const { signInWithPassword, signInWithGoogle, error: authError } = useAuth();
  const colors = useThemeColors();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const error = localError ?? authError;

  async function handlePasswordSignIn() {
    setLocalError(null);
    setBusy(true);
    try {
      await signInWithPassword(email.trim(), password);
      // On success the AuthProvider flips status; app/index.tsx redirects.
    } catch (e) {
      setLocalError(
        e instanceof Error ? e.message : "Sign-in failed. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleGoogleSignIn() {
    setLocalError(null);
    setBusy(true);
    try {
      await signInWithGoogle();
    } catch (e) {
      // A cancel is not an error worth surfacing loudly.
      if (!(e instanceof SignInCancelledError)) {
        setLocalError(
          e instanceof Error ? e.message : "Sign-in failed. Please try again.",
        );
      }
    } finally {
      setBusy(false);
    }
  }

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
                  Welcome to Onyx
                </Text>
                <Text font="main-ui-muted" color="text-03">
                  Your open source AI platform for work
                </Text>
              </View>
            </View>

            <Button
              variant="default"
              prominence="secondary"
              onPress={handleGoogleSignIn}
              disabled={busy}
              leftIcon={<GoogleLogo size={18} />}
            >
              Continue with Google
            </Button>

            <View className="flex-row items-center gap-2">
              <View className="h-[1px] flex-1 bg-border-01" />
              <Text font="secondary-body" color="text-03">
                or
              </Text>
              <View className="h-[1px] flex-1 bg-border-01" />
            </View>

            <View className="gap-3">
              <View className="gap-1">
                <Text font="secondary-body" color="text-04">
                  Email Address
                </Text>
                <TextInput
                  className="rounded-[8px] border border-border-02 px-3 py-2 text-text-05"
                  placeholder="email@yourcompany.com"
                  placeholderTextColor={colors["text-03"]}
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="email-address"
                  textContentType="emailAddress"
                  value={email}
                  onChangeText={setEmail}
                  editable={!busy}
                />
              </View>

              <View className="gap-1">
                <Text font="secondary-body" color="text-04">
                  Password
                </Text>
                <TextInput
                  className="rounded-[8px] border border-border-02 px-3 py-2 text-text-05"
                  placeholder="••••••••"
                  placeholderTextColor={colors["text-03"]}
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry
                  textContentType="password"
                  value={password}
                  onChangeText={setPassword}
                  editable={!busy}
                />
              </View>

              <Button onPress={handlePasswordSignIn} disabled={busy}>
                {busy ? "Signing in…" : "Sign In"}
              </Button>

              {error ? (
                <Text font="secondary-body" color="status-text-error-05">
                  {error}
                </Text>
              ) : null}
            </View>
          </View>

          <View className="flex-row items-center justify-center">
            <Text font="main-ui-body" color="text-03">
              New to Onyx?{" "}
            </Text>
            <Pressable
              onPress={() => router.push("/(auth)/register" as never)}
              disabled={busy}
            >
              <Text
                font="main-ui-action"
                color="text-05"
                style={{ textDecorationLine: "underline" }}
              >
                Create an Account
              </Text>
            </Pressable>
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
