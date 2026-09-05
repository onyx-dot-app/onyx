"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("craft.apps.oauthCallback");
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
      setErrorMessage(t("errors.cancelled", { reason: slackError }));
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setErrorMessage(t("errors.missingParams"));
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
  }, [code, state, slackError, router, t]);

  return (
    <SettingsLayouts.Root width="sm">
      <SettingsLayouts.Header
        icon={SvgPlug}
        title={t("title")}
        description={t("description")}
      />
      <SettingsLayouts.Body>
        <Card background="light" border="solid" rounding={4}>
          <div className="flex flex-col gap-2">
            {status === "exchanging" && (
              <Text font="main-content-body">{t("exchanging.label")}</Text>
            )}
            {status === "success" && (
              <Text font="main-content-body">{t("success.label")}</Text>
            )}
            {status === "error" && (
              <>
                <Text font="main-content-body">{t("errors.failed")}</Text>
                {errorMessage && (
                  <Text font="secondary-body" color="text-03">
                    {errorMessage}
                  </Text>
                )}
                <div className="pt-2">
                  <Button onClick={() => router.push(CRAFT_APPS_PATH as Route)}>
                    {t("backButton")}
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
