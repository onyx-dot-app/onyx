"use client";

import { useNavigation, useSearchParams } from "@opal/navigation";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { mutate as globalMutate } from "swr";
import { SettingsLayouts } from "@opal/layouts";
import { Button, Card, Text } from "@opal/components";
import { SvgPlug } from "@opal/icons";
import { CRAFT_PLUGINS_PATH } from "@/app/craft/v1/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { completeExternalAppOAuthCallback } from "@/app/craft/services/externalAppsService";
import { OAUTH_POPUP_MESSAGE_SOURCE } from "@/app/craft/types/setupRequests";
import { withDesktopOAuthHandoff } from "@/sections/oauth/DesktopOAuthHandoff";
import {
  leaveOAuthCallback,
  notifyOAuthComplete,
  reportOAuthCallback,
} from "@/lib/oauth/launch";

type Status = "exchanging" | "success" | "error";

function ExternalAppsOAuthCallbackPageContent() {
  const t = useTranslations("craft.apps.oauthCallback");
  const navigation = useNavigation();
  const params = useSearchParams();
  const code = params.get("code") ?? null;
  const state = params.get("state") ?? null;
  const slackError = params.get("error") ?? null;

  const [status, setStatus] = useState<Status>("exchanging");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // OAuth `code` is single-use — gate against React Strict Mode and
  // remount-induced double exchanges, which would 400 on the second.
  const hasExchanged = useRef(false);

  useEffect(() => {
    // Once the exchange starts, the URL is the redirect's, not Slack's: its
    // missing `code` and `state` are not an error.
    if (hasExchanged.current) return;
    if (slackError) {
      const description = t("errors.cancelled", { reason: slackError });
      if (
        state &&
        reportOAuthCallback(state, false, undefined, {
          title: t("errors.failed"),
          description,
        })
      )
        return;
      setStatus("error");
      setErrorMessage(description);
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setErrorMessage(t("errors.missingParams"));
      return;
    }
    hasExchanged.current = true;

    async function exchange(code: string, state: string) {
      try {
        const { external_app_id, return_path } =
          await completeExternalAppOAuthCallback(code, state);
        setStatus("success");
        if (return_path) {
          const target = new URL(return_path, window.location.origin);
          if (
            target.origin !== window.location.origin ||
            target.pathname !== "/app/plugins/oauth/complete"
          ) {
            throw new Error(t("errors.missingParams"));
          }
          // The member plugin dialog waits on this state; it verifies the
          // connection itself.
          if (reportOAuthCallback(state, true)) return;
          target.searchParams.set("message", "oauth_connected");
          navigation.go(`${target.pathname}?${target.searchParams}`, {
            replace: true,
          });
          return;
        }
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
          notifyOAuthComplete(state);
          window.close();
          return;
        }
        if (reportOAuthCallback(state, true)) return;
        await globalMutate(SWR_KEYS.buildExternalApps);
        setTimeout(
          () =>
            navigation.go(
              `${CRAFT_PLUGINS_PATH}?actionPolicies=app-${external_app_id}`
            ),
          800
        );
      } catch (e) {
        const description = e instanceof Error ? e.message : String(e);
        if (
          reportOAuthCallback(state, false, undefined, {
            title: t("errors.failed"),
            description,
          })
        )
          return;
        setStatus("error");
        setErrorMessage(description);
      }
    }

    exchange(code, state);
  }, [code, state, slackError, navigation, t]);

  return (
    <SettingsLayouts.Root width="sm">
      <SettingsLayouts.Header
        icon={SvgPlug}
        title={t("title")}
        description={t("description")}
      />
      <SettingsLayouts.Body>
        <Card color="background-tint-00" border="solid" rounding={4}>
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
                  <Button
                    onClick={() =>
                      leaveOAuthCallback(() =>
                        navigation.go(CRAFT_PLUGINS_PATH)
                      )
                    }
                  >
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

export default withDesktopOAuthHandoff(ExternalAppsOAuthCallbackPageContent);
