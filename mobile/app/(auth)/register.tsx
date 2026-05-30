import { useState } from "react";
import { TextInput, View } from "react-native";
import { router } from "expo-router";

import { useAuth, RegistrationError } from "@/auth";
import { Text, Button } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";

// In-app registration. POSTs JSON { email, password } to the backend register
// route. We do NOT sign the user in here: the backend may require email
// verification first, so on success we show a "check your email, then sign in"
// confirmation and offer a button back to the login screen.
export default function Register() {
  const { register } = useAuth();
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

  if (done) {
    return (
      <View className="flex-1 justify-center gap-4 bg-background-neutral-00 p-6">
        <Text font="heading-h2" color="text-05">
          Account created
        </Text>
        <Text font="main-ui-body" color="text-03">
          Check your email to verify your account (if required), then sign in.
        </Text>
        <Button onPress={() => router.replace("/(auth)/login" as never)}>
          Go to sign in
        </Button>
      </View>
    );
  }

  return (
    <View className="flex-1 justify-center gap-4 bg-background-neutral-00 p-6">
      <View className="items-center gap-1">
        <Text font="heading-h1" color="text-05">
          Create account
        </Text>
        <Text font="main-ui-body" color="text-03">
          Sign up for Onyx
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
          className="border border-border-02 rounded-[8px] px-3 py-2 text-text-05"
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
        {busy ? "Creating…" : "Create account"}
      </Button>

      <Button
        variant="default"
        prominence="tertiary"
        onPress={() => router.replace("/(auth)/login" as never)}
        disabled={busy}
      >
        Back to sign in
      </Button>

      {error ? (
        <Text font="secondary-body" color="status-text-error-05">
          {error}
        </Text>
      ) : null}
    </View>
  );
}
