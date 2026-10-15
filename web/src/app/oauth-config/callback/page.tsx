"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { MessageCard } from "@opal/components";
import OAuthCallbackPage from "@/components/oauth/OAuthCallbackPage";
import OAuthTestCallback from "@/sections/actions/oauth/OAuthTestCallback";
import { OAUTH_TEST_ACTIVE_KEY } from "@/lib/oauth/testConnection";

export default function OAuthConfigCallbackPage() {
  const t = useTranslations("actions.openApiAuthModal.connectionCheck");
  const [mode, setMode] = useState<
    { kind: "test"; state: string } | { kind: "normal" | "completed" } | null
  >(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const completed = params.has("oauth_test_completed");
    let state: string | null = null;
    try {
      state = window.sessionStorage.getItem(OAUTH_TEST_ACTIVE_KEY);
    } catch {
      /* Normal callbacks do not require browser storage. */
    }
    setMode(
      completed
        ? { kind: "completed" }
        : state && state === params.get("state")
          ? { kind: "test", state }
          : { kind: "normal" }
    );
  }, []);
  if (mode?.kind === "normal")
    return (
      <OAuthCallbackPage
        config={{
          callbackApiUrl: "/api/oauth-config/callback",
          defaultRedirectPath: "/app",
          processingMessage: "Completing Authorization...",
          processingDetails:
            "Please wait while we securely store your credentials.",
          successMessage: "Authorization Successful!",
          successDetailsTemplate:
            "You have successfully authorized the tool to access your {serviceName} account.",
          errorMessage: "Authorization Failed",
          backButtonText: "Back to Chat",
          autoRedirectDelay: 2000,
        }}
      />
    );
  if (mode?.kind === "test")
    return <OAuthTestCallback expectedState={mode.state} />;
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <MessageCard
        variant={mode ? "info" : "pending"}
        title={t(mode ? "returnToSettings" : "testing")}
      />
    </div>
  );
}
