"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, MessageCard } from "@opal/components";
import { completeOAuthTest } from "@/lib/oauth/api";
import {
  OAUTH_TEST_ACTIVE_KEY,
  OAUTH_TEST_MESSAGE_TYPE,
  oauthTestStorageKey,
  oauthTestChannelName,
  type OAuthTestMessage,
  type OAuthTestResult,
} from "@/lib/oauth/testConnection";

interface OAuthTestCallbackProps {
  expectedState: string;
}

export default function OAuthTestCallback({
  expectedState,
}: OAuthTestCallbackProps) {
  const t = useTranslations("actions.openApiAuthModal.connectionCheck");
  const query = useSearchParams();
  const [result, setResult] = useState<OAuthTestResult | null>(null);
  const completion = useRef<Promise<OAuthTestResult> | null>(null);
  const code = query?.get("code");
  const state = query?.get("state");
  const error = query?.get("error");

  useEffect(() => {
    let subscribed = true;
    if (!completion.current) {
      completion.current = (async (): Promise<OAuthTestResult> => {
        try {
          if (
            window.sessionStorage.getItem(
              oauthTestStorageKey(expectedState)
            ) !== "pending"
          ) {
            return { status: "interrupted" };
          }
          window.sessionStorage.setItem(
            oauthTestStorageKey(expectedState),
            "exchanging"
          );
          if (state !== expectedState || !state) return { status: "failed" };
          if (error) return { status: "denied" };
          if (!code) return { status: "failed" };
          return {
            status: "success",
            supports_pkce: await completeOAuthTest(code, state),
          };
        } catch {
          return { status: "failed" };
        }
      })();
    }
    completion.current.then((outcome) => {
      if (!subscribed) return;
      setResult(outcome);
      // Remove the code and marker before reporting; reloading cannot redeem twice.
      window.history.replaceState(
        null,
        "",
        "/oauth-config/callback?oauth_test_completed=1"
      );
      try {
        window.sessionStorage.removeItem(oauthTestStorageKey(expectedState));
        window.sessionStorage.removeItem(OAUTH_TEST_ACTIVE_KEY);
      } catch {
        /* The popup still reports the result if storage becomes unavailable. */
      }
      const message: OAuthTestMessage = {
        type: OAUTH_TEST_MESSAGE_TYPE,
        state: expectedState,
        result: outcome,
      };
      if (typeof BroadcastChannel !== "undefined") {
        try {
          const channel = new BroadcastChannel(
            oauthTestChannelName(expectedState)
          );
          channel.postMessage(message);
          channel.close();
        } catch {
          // Retain the opener fallback when browser channels are unavailable.
        }
      }
      window.opener?.postMessage(message, window.location.origin);
    });
    return () => {
      subscribed = false;
    };
  }, [code, state, error, expectedState]);

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <MessageCard
        variant={
          !result
            ? "pending"
            : result.status === "success"
              ? "success"
              : "warning"
        }
        title={
          !result
            ? t("testing")
            : result.status === "success"
              ? t(result.supports_pkce ? "successPkce" : "success")
              : t(`result.${result.status}`)
        }
        description={t("returnToSettings")}
        bottomChildren={
          <Button prominence="secondary" onClick={() => window.close()}>
            {t("close")}
          </Button>
        }
      />
    </div>
  );
}
