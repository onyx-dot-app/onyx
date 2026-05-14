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

  // OAuth `code` is single-use — gate against React Strict Mode and
  // remount-induced double exchanges, which would 400 on the second.
  const hasExchanged = useRef(false);

  useEffect(() => {
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
        await globalMutate(SWR_KEYS.buildExternalApps);
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
