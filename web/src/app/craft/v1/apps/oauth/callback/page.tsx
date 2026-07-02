"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { mutate as globalMutate } from "swr";
import { SettingsLayouts } from "@opal/layouts";
import { Button, Card, Text } from "@opal/components";
import { SvgPlug } from "@opal/icons";
import { CRAFT_APPS_PATH } from "@/app/craft/v1/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { completeExternalAppOAuthCallback } from "@/app/craft/services/externalAppsService";
import { OAUTH_POPUP_MESSAGE_SOURCE } from "@/app/craft/types/setupRequests";

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
        const { external_app_id } = await completeExternalAppOAuthCallback(
          code!,
          state!
        );
        setStatus("success");
        // Launched from the in-chat SetupCard popup: signal the opener and close
        // immediately — before any await — so the opener's close-poll can't race
        // ahead of the message and treat the close as a cancellation.
        if (window.opener) {
          window.opener.postMessage(
            {
              source: OAUTH_POPUP_MESSAGE_SOURCE,
              externalAppId: external_app_id,
            },
            window.location.origin
          );
          window.close();
          return;
        }
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
        <Card background="light" border="solid" rounding="lg">
          <div className="flex flex-col gap-2">
            {status === "exchanging" && (
              <Text font="main-content-body">
                Exchanging authorization code…
              </Text>
            )}
            {status === "success" && (
              <Text font="main-content-body">
                Connected. Redirecting back to your apps…
              </Text>
            )}
            {status === "error" && (
              <>
                <Text font="main-content-body">Connection failed.</Text>
                {errorMessage && (
                  <Text font="secondary-body" color="text-03">
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
