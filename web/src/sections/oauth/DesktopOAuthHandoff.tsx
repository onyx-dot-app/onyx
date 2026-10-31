"use client";

import { type ComponentType, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, Card } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgConnected } from "@opal/illustrations";
import {
  desktopOAuthReturnUrl,
  needsDesktopOAuthHandoff,
} from "@/lib/oauth/launch";

/** Hands a desktop-started OAuth callback from the browser back to the app. */
export function DesktopOAuthHandoff() {
  const t = useTranslations("common.oauthCallback.desktopHandoff");
  const [returnUrl, setReturnUrl] = useState<string | null>(null);

  useEffect(() => {
    const url = desktopOAuthReturnUrl(new URL(window.location.href));
    setReturnUrl(url);
    window.location.assign(url);
  }, []);

  return (
    <Section justifyContent="center" padding={4} className="min-h-screen">
      <div className="w-full max-w-md">
        <Card
          padding={6}
          rounding={4}
          color="background-tint-00"
          border="solid"
        >
          <Section alignItems="stretch" gap={4} padding={0} height="auto">
            <IllustrationContent
              illustration={SvgConnected}
              title={t("title")}
              description={t("description")}
            />
            <Button
              width="full"
              disabled={returnUrl === null}
              onClick={() => returnUrl && window.location.assign(returnUrl)}
            >
              {t("button")}
            </Button>
          </Section>
        </Card>
      </div>
    </Section>
  );
}

/** Renders the desktop handoff instead of a callback page when needed. */
export function withDesktopOAuthHandoff<P extends object>(
  CallbackPage: ComponentType<P>
): ComponentType<P> {
  function DesktopAwareCallbackPage(props: P) {
    const state = useSearchParams()?.get("state") ?? null;
    if (needsDesktopOAuthHandoff(state)) return <DesktopOAuthHandoff />;
    return <CallbackPage {...props} />;
  }
  return DesktopAwareCallbackPage;
}
