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
import { API_PATHS } from "@/lib/api/endpoints";
import type { AuthTypeResponse } from "@/lib/types/auth";
import { useSimpleQuery } from "@/query/client";

// Mirrors web AuthFlowContainer: discover the server's auth type, then render only the
// methods it supports. Password creds hit the mobile Bearer login route; Google opens
// the system browser. OIDC/SAML aren't wired on mobile yet.
export default function Login() {
  const { signInWithPassword, error: authError } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const error = localError ?? authError;

  const {
    data: authMeta,
    isLoading: authLoading,
    isError: authMetaFailed,
  } = useSimpleQuery<AuthTypeResponse>(API_PATHS.authType);

  const authType = authMeta?.auth_type;
  const showGoogle = authType === "google_oauth" || authType === "cloud";
  const showPassword = authType === "basic" || authType === "cloud";
  const ssoOnly = authType === "oidc" || authType === "saml";

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
        showPassword ? (
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
        ) : undefined
      }
    >
      {authLoading ? (
        <Text font="main-ui-body" color="text-03">
          Loading sign-in options…
        </Text>
      ) : authMetaFailed || !authType ? (
        <Text font="secondary-body" color="status-text-error-05">
          Couldn&apos;t load sign-in options. Check the server address and try again.
        </Text>
      ) : ssoOnly ? (
        <Text font="main-ui-body" color="text-03">
          This server uses SSO sign-in, which isn&apos;t supported in the mobile app
          yet.
        </Text>
      ) : (
        <>
          {showGoogle ? (
            <Button
              variant="default"
              prominence="secondary"
              onPress={handleGoogleSignIn}
              disabled={busy}
              leftIcon={<GoogleLogo size={18} />}
            >
              Continue with Google
            </Button>
          ) : null}

          {showGoogle && showPassword ? <OrDivider /> : null}

          {showPassword ? (
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
          ) : null}
        </>
      )}
    </AuthCard>
  );
}
