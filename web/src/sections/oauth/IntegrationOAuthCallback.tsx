"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, OnyxLoader } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgConnected, SvgPlugBroken } from "@opal/illustrations";
import { loadPage, useNavigation, useSearchParams } from "@opal/navigation";
import { validateInternalRedirect } from "@/lib/auth/utils";
import { completeIntegrationOAuth } from "@/lib/integrations/svc";
import { leaveOAuthCallback, reportOAuthCallback } from "@/lib/oauth/launch";
import { withDesktopOAuthHandoff } from "@/sections/oauth/DesktopOAuthHandoff";
import { customizeTabHref } from "@/lib/customize/paths";

const FALLBACK_PATH = customizeTabHref("integrations");

type CallbackState =
  | { phase: "processing" }
  | { phase: "success"; redirectPath: string }
  | { phase: "error"; description: string };

/**
 * The OAuth callback of an integration sign-in. It sends the code to the
 * integration API, tells the waiting tab, and goes to the return path that
 * the sign-in started with.
 */
function IntegrationOAuthCallbackContent() {
  const t = useTranslations("plugins.member.oauthCallback");
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const [state, setState] = useState<CallbackState>({ phase: "processing" });
  // The code is single-use: a second POST (Strict Mode, a remount) fails.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = searchParams.get("code");
    const attempt = searchParams.get("state");
    const providerError = searchParams.get("error");

    if (providerError) {
      const description =
        searchParams.get("error_description") || t("cancelled");
      if (
        attempt &&
        reportOAuthCallback(attempt, false, undefined, {
          title: t("errorTitle"),
          description,
        })
      )
        return;
      setState({ phase: "error", description });
      return;
    }
    if (!code || !attempt) {
      setState({ phase: "error", description: t("invalidLink") });
      return;
    }

    completeIntegrationOAuth(code, attempt).then(
      (result) => {
        const redirectPath =
          validateInternalRedirect(result.return_path) ?? FALLBACK_PATH;
        if (reportOAuthCallback(attempt, true, redirectPath)) return;
        setState({ phase: "success", redirectPath });
        leaveOAuthCallback(() => loadPage(redirectPath, { replace: true }));
      },
      (error: unknown) => {
        const description =
          error instanceof Error && error.message ? error.message : t("failed");
        if (
          reportOAuthCallback(attempt, false, undefined, {
            title: t("errorTitle"),
            description,
          })
        )
          return;
        setState({ phase: "error", description });
      }
    );
  }, [navigation, searchParams, t]);

  return (
    <Section justifyContent="center" padding={4} className="min-h-screen">
      <Section width={28} height="auto">
        <Card
          padding={6}
          rounding={4}
          color="background-tint-00"
          border="solid"
        >
          <Section alignItems="stretch" gap={4} height="auto">
            {state.phase === "processing" && (
              <Section gap={3} height="auto" padding={5}>
                <OnyxLoader />
                <IllustrationContent title={t("processing")} />
              </Section>
            )}
            {state.phase === "success" && (
              <IllustrationContent
                illustration={SvgConnected}
                title={t("successTitle")}
                description={t("successDescription")}
              />
            )}
            {state.phase === "error" && (
              <>
                <IllustrationContent
                  illustration={SvgPlugBroken}
                  title={t("errorTitle")}
                  description={state.description}
                />
                <Button
                  width="full"
                  onClick={() =>
                    leaveOAuthCallback(() => navigation.go(FALLBACK_PATH))
                  }
                >
                  {t("back.label")}
                </Button>
              </>
            )}
          </Section>
        </Card>
      </Section>
    </Section>
  );
}

const IntegrationOAuthCallback = withDesktopOAuthHandoff(
  IntegrationOAuthCallbackContent
);
export default IntegrationOAuthCallback;
