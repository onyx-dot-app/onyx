"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { mutate as globalMutate } from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { SvgPlug } from "@opal/icons";
import { CRAFT_APPS_PATH } from "@/app/craft/v1/constants";
import { SWR_KEYS } from "@/lib/swr-keys";

type Status = "exchanging" | "success" | "error";

export default function ExternalAppsOAuthCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const code = params?.get("code") ?? null;
  const state = params?.get("state") ?? null;
  const slackError = params?.get("error") ?? null;

  const [status, setStatus] = useState<Status>("exchanging");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // OAuth `code` is single-use: Slack invalidates it on first
  // redemption, so a second POST gets `invalid_code`. React Strict
  // Mode (and any retry / remount) would otherwise fire the exchange
  // twice. A ref survives effect re-runs within the same component
  // mount and gates the network call to exactly one.
  const hasExchanged = useRef(false);

  useEffect(() => {
    // Slack appends ?error=access_denied (or similar) when a user
    // cancels consent. Surface that instead of trying the exchange.
    if (slackError) {
      setStatus("error");
      setErrorMessage(`OAuth was cancelled or denied: ${slackError}`);
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setErrorMessage("Missing code or state in callback URL.");
      return;
    }
    if (hasExchanged.current) return;
    hasExchanged.current = true;

    async function exchange() {
      try {
        const res = await fetch("/api/build/apps/oauth/callback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, state }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          setStatus("error");
          setErrorMessage(
            data.detail ?? `OAuth exchange failed (HTTP ${res.status}).`
          );
          return;
        }
        setStatus("success");
        // Invalidate the user-apps SWR cache so /craft/v1/apps refetches
        // and shows "Connected" instead of "Connect" when we land there.
        await globalMutate(SWR_KEYS.buildExternalApps);
        // Brief pause so the user sees the success state before redirect.
        setTimeout(() => router.push(CRAFT_APPS_PATH as Route), 800);
      } catch (e) {
        setStatus("error");
        setErrorMessage(e instanceof Error ? e.message : String(e));
      }
    }

    exchange();
  }, [code, state, slackError, router]);

  return (
    <SettingsLayouts.Root width="sm">
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="Connecting your app"
        description="Finishing the OAuth handshake…"
      />
      <SettingsLayouts.Body>
        <Card>
          <div className="flex flex-col gap-2">
            {status === "exchanging" && (
              <Text mainContentBody>Exchanging authorization code…</Text>
            )}
            {status === "success" && (
              <Text mainContentBody>
                Connected. Redirecting back to your apps…
              </Text>
            )}
            {status === "error" && (
              <>
                <Text mainContentBody>Connection failed.</Text>
                {errorMessage && (
                  <Text secondaryBody text03>
                    {errorMessage}
                  </Text>
                )}
                <div className="pt-2">
                  <Button onClick={() => router.push(CRAFT_APPS_PATH as Route)}>
                    Back to My Apps
                  </Button>
                </div>
              </>
            )}
          </div>
        </Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
