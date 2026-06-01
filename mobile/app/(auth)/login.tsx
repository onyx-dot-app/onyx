import { useState } from "react";
import { Pressable, View } from "react-native";
import { router } from "expo-router";

import { useAuth } from "@/auth";
import { AuthCard } from "@/components/auth/AuthCard";
import { AuthTextField } from "@/components/auth/AuthTextField";
import { OrDivider } from "@/components/auth/OrDivider";
import { useGoogleSignIn } from "@/components/auth/useGoogleSignIn";
import { Text, Button } from "@/components/opal";
import { GoogleLogo } from "@/components/ui/logos";

// Sign-in screen. Mirrors the web auth layout (web/src/components/auth/
// AuthFlowContainer + app/auth/login): an Onyx-logo-topped card with a
// "Continue with Google" button, an "or" divider, and the email/password form.
// Password creds post to the backend's mobile Bearer login route, which returns
// a JWT the AuthProvider stores; on success status flips to signedIn and
// app/index.tsx routes into (app). "Create an Account" pushes the registration
// screen.
export default function Login() {
  const { signInWithPassword, error: authError } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const error = localError ?? authError;

  const handleGoogleSignIn = useGoogleSignIn(setLocalError, setBusy);

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

  return (
    <AuthCard
      title="Welcome to Onyx"
      subtitle="Your open source AI platform for work"
      footer={
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
      }
    >
      <Button
        variant="default"
        prominence="secondary"
        onPress={handleGoogleSignIn}
        disabled={busy}
        leftIcon={<GoogleLogo size={18} />}
      >
        Continue with Google
      </Button>

      <OrDivider />

      <View className="gap-3">
        <AuthTextField
          label="Email Address"
          placeholder="email@yourcompany.com"
          keyboardType="email-address"
          textContentType="emailAddress"
          value={email}
          onChangeText={setEmail}
          editable={!busy}
        />

        <AuthTextField
          label="Password"
          placeholder="••••••••"
          secureTextEntry
          textContentType="password"
          value={password}
          onChangeText={setPassword}
          editable={!busy}
        />

        <Button onPress={handlePasswordSignIn} disabled={busy}>
          {busy ? "Signing in…" : "Sign In"}
        </Button>

        {error ? (
          <Text font="secondary-body" color="status-text-error-05">
            {error}
          </Text>
        ) : null}
      </View>
    </AuthCard>
  );
}
