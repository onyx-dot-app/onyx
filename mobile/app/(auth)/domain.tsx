import { useState } from "react";
import { View } from "react-native";
import { router } from "expo-router";

import { useAuth } from "@/auth";
import { AuthCard } from "@/components/auth/AuthCard";
import { AuthTextField } from "@/components/auth/AuthTextField";
import { Text, Button } from "@/components/opal";
import { setServerUrl } from "@/lib/serverUrl";

// Step 1 of the login funnel: point the app at an Onyx server (like the desktop app's
// "Root Domain" field). Validates reachability via /health, persists the URL, then
// re-runs hydration so the gate moves to the auth-method screen.
export default function Domain() {
  const { refresh } = useAuth();

  const [url, setUrl] = useState("https://");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConnect() {
    setError(null);
    const candidate = url.trim().replace(/\/+$/, "");
    if (!/^https?:\/\/.+/i.test(candidate)) {
      setError("Enter a full URL, e.g. https://cloud.onyx.app");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${candidate}/health`);
      if (!res.ok) throw new Error("unreachable");
      await setServerUrl(candidate);
      await refresh(); // noDomain -> signedOut, picks up the new base URL
      router.replace("/(auth)/login" as never);
    } catch {
      setError("Couldn't reach that server. Check the address and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Connect to Onyx"
      subtitle="Enter your Onyx server address to get started"
    >
      <View className="gap-3">
        <AuthTextField
          label="Server URL"
          placeholder="https://cloud.onyx.app"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          textContentType="URL"
          value={url}
          onChangeText={setUrl}
          editable={!busy}
        />

        <Button onPress={handleConnect} disabled={busy}>
          {busy ? "Connecting…" : "Connect"}
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
