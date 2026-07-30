// Probes the URL via /auth/type before committing it.
import { router } from "expo-router";
import { useState } from "react";
import { View } from "react-native";

import {
  ONYX_CLOUD_URL,
  normalizeServerUrl,
  probeAuthType,
} from "@/api/auth/instanceUrl";
import { getErrorMessage } from "@/api/errors";
import { AuthScreenShell } from "@/components/auth/AuthScreenShell";
import { InputLayouts, TextInput } from "@/components/form";
import { Button } from "@/components/ui/button";
import { useSession } from "@/state/session";

export default function ConnectScreen() {
  const serverUrl = useSession((state) => state.serverUrl);
  const setServerUrl = useSession((state) => state.setServerUrl);

  // Default to cloud: cloud users tap through, self-hosted overwrite.
  const [url, setUrl] = useState(serverUrl ?? ONYX_CLOUD_URL);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function connect(candidate: string) {
    setError(null);
    let normalized: string;
    try {
      normalized = normalizeServerUrl(candidate);
    } catch (validationError) {
      setError(getErrorMessage(validationError));
      return;
    }

    setBusy(true);
    try {
      await probeAuthType(normalized);
    } catch (probeError) {
      setError(getErrorMessage(probeError));
      setBusy(false);
      return;
    }
    // busy stays true: the screen unmounts on navigation, nothing to reset.
    setServerUrl(normalized);
    router.replace("/(auth)/login");
  }

  return (
    <AuthScreenShell title="Connect to Onyx">
      <InputLayouts.Vertical
        title="Root Domain"
        description="The root URL for your Onyx instance"
        error={error ?? undefined}
      >
        <TextInput
          value={url}
          onChangeText={(text) => {
            setUrl(text);
            if (error) setError(null);
          }}
          variant={error ? "error" : "idle"}
          placeholder={ONYX_CLOUD_URL}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          inputMode="url"
          autoComplete="url"
          returnKeyType="go"
          onSubmitEditing={() => connect(url)}
        />
      </InputLayouts.Vertical>

      <View className="mt-16">
        <Button
          width="full"
          disabled={url.trim().length === 0}
          loading={busy}
          onPress={() => connect(url)}
        >
          {busy ? "Connecting…" : "Save & Connect"}
        </Button>
      </View>
    </AuthScreenShell>
  );
}
