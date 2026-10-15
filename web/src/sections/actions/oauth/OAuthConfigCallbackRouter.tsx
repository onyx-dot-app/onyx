"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { MessageCard } from "@opal/components";
import OAuthTestCallback from "@/sections/actions/oauth/OAuthTestCallback";
import { OAUTH_TEST_ACTIVE_KEY } from "@/lib/oauth/testConnection";

export default function OAuthConfigCallbackRouter({
  children,
}: {
  children: ReactNode;
}) {
  const t = useTranslations("actions.openApiAuthModal.connectionCheck");
  const [mode, setMode] = useState<
    { kind: "test"; state: string } | { kind: "normal" | "completed" } | null
  >(null);
  useEffect(() => {
    const completed = new URLSearchParams(window.location.search).has(
      "oauth_test_completed"
    );
    let state: string | null = null;
    try {
      state = window.sessionStorage.getItem(OAUTH_TEST_ACTIVE_KEY);
    } catch {
      /* Normal callbacks do not require browser storage. */
    }
    setMode(
      completed
        ? { kind: "completed" }
        : state
          ? { kind: "test", state }
          : { kind: "normal" }
    );
  }, []);
  if (mode?.kind === "normal") return children;
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
