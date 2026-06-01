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

// In-app registration. Mirrors web signup: Onyx-logo card, Google button, "or"
// divider, email/password form. POSTs JSON { email, password } to
// the backend register route. We do NOT sign the user in here: the backend may
// require email verification first, so on success we swap the card to a "check
// your email, then sign in" confirmation and offer a button back to login.
export default function Register() {
  const { register } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleGoogleSignIn = useGoogleSignIn(setError, setBusy);

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
        e instanceof Error ? e.message : "Could not create your account.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title={done ? "Account created" : "Create account"}
      subtitle={
        done
          ? "Check your email to verify your account (if required), then sign in."
          : "Get started with Onyx"
      }
      footer={
        !done && (
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
        )
      }
    >
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
              textContentType="newPassword"
              value={password}
              onChangeText={setPassword}
              editable={!busy}
            />

            <AuthTextField
              label="Confirm password"
              placeholder="••••••••"
              secureTextEntry
              textContentType="newPassword"
              value={confirm}
              onChangeText={setConfirm}
              editable={!busy}
            />

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
    </AuthCard>
  );
}
