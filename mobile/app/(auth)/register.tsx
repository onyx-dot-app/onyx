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

import { useAuth, RegistrationError, SignInCancelledError } from "@/auth";
import { Text, Button } from "@/components/opal";
import { GoogleLogo, OnyxLogo } from "@/components/ui/logos";
import { useThemeColors } from "@/theme/ThemeProvider";

// In-app registration. Mirrors the web signup layout (Onyx-logo card, Google
// button, "or" divider, email/password form). POSTs JSON { email, password } to
// the backend register route. We do NOT sign the user in here: the backend may
// require email verification first, so on success we swap the card to a "check
// your email, then sign in" confirmation and offer a button back to login.
export default function Register() {
  const { register, signInWithGoogle } = useAuth();
  const colors = useThemeColors();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleRegister() {
    setError(null);

    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    if (!email.trim() || !password) {
      setError("Enter an email and password.");
      return;
    }

    setBusy(true);
    try {
      await register(email.trim(), password);
      // Whether or not verification is required, the next step is to sign in, so
      // a single confirmation copy covers both cases.
      setDone(true);
    } catch (e) {
      setError(
        e instanceof RegistrationError
          ? e.message
          : e instanceof Error
            ? e.message
            : "Could not create your account.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleGoogleSignIn() {
    setError(null);
    setBusy(true);
    try {
      await signInWithGoogle();
    } catch (e) {
      // A cancel is not an error worth surfacing loudly.
      if (!(e instanceof SignInCancelledError)) {
        setError(
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
                  {done ? "Account created" : "Create account"}
                </Text>
                <Text font="main-ui-muted" color="text-03">
                  {done
                    ? "Check your email to verify your account (if required), then sign in."
                    : "Get started with Onyx"}
                </Text>
              </View>
            </View>

            {done ? (
              <Button onPress={() => router.replace("/(auth)/login" as never)}>
                Go to sign in
              </Button>
            ) : (
              <>
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
                      textContentType="newPassword"
                      value={password}
                      onChangeText={setPassword}
                      editable={!busy}
                    />
                  </View>

                  <View className="gap-1">
                    <Text font="secondary-body" color="text-04">
                      Confirm password
                    </Text>
                    <TextInput
                      className="rounded-[8px] border border-border-02 px-3 py-2 text-text-05"
                      placeholder="••••••••"
                      placeholderTextColor={colors["text-03"]}
                      autoCapitalize="none"
                      autoCorrect={false}
                      secureTextEntry
                      textContentType="newPassword"
                      value={confirm}
                      onChangeText={setConfirm}
                      editable={!busy}
                    />
                  </View>

                  <Button onPress={handleRegister} disabled={busy}>
                    {busy ? "Creating…" : "Create Account"}
                  </Button>

                  {error ? (
                    <Text font="secondary-body" color="status-text-error-05">
                      {error}
                    </Text>
                  ) : null}
                </View>
              </>
            )}
          </View>

          {!done && (
            <View className="flex-row items-center justify-center">
              <Text font="main-ui-body" color="text-03">
                Already have an account?{" "}
              </Text>
              <Pressable
                onPress={() => router.replace("/(auth)/login" as never)}
                disabled={busy}
              >
                <Text
                  font="main-ui-action"
                  color="text-05"
                  style={{ textDecorationLine: "underline" }}
                >
                  Sign In
                </Text>
              </Pressable>
            </View>
          )}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
