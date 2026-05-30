import { useState } from "react";
import { TextInput, View } from "react-native";
import { router } from "expo-router";

import { useAuth, SignInCancelledError } from "@/auth";
import { Text, Button } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";

// Sign-in screen. Two real inputs (email/password) post form-urlencoded creds to
// the backend's mobile Bearer login route, which returns a JWT the AuthProvider
// stores; on success status flips to signedIn and app/index.tsx routes into (app).
// A "Sign in with Google" button runs the system-browser OAuth flow, and a
// "Create account" link pushes the in-app registration screen.
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
    <View className="flex-1 justify-center gap-4 bg-background-neutral-00 p-6">
      <View className="items-center gap-1">
        <Text font="heading-h1" color="text-05">
          Onyx
        </Text>
        <Text font="main-ui-body" color="text-03">
          Sign in to continue
        </Text>
      </View>

      <View className="gap-1">
        <Text font="secondary-body" color="text-04">
          Email
        </Text>
        <TextInput
          className="border border-border-02 rounded-[8px] px-3 py-2 text-text-05"
          placeholder="you@example.com"
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
          className="border border-border-02 rounded-[8px] px-3 py-2 text-text-05"
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
        {busy ? "Signing in…" : "Sign in"}
      </Button>

      <Button
        variant="default"
        prominence="secondary"
        onPress={handleGoogleSignIn}
        disabled={busy}
      >
        Sign in with Google
      </Button>

      <Button
        variant="default"
        prominence="tertiary"
        onPress={() => router.push("/(auth)/register" as never)}
        disabled={busy}
      >
        Create account
      </Button>

      {error ? (
        <Text font="secondary-body" color="status-text-error-05">
          {error}
        </Text>
      ) : null}
    </View>
  );
}
