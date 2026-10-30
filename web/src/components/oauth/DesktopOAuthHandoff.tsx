"use client";

import { type ComponentType, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, Card } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
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
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <Card
          padding={6}
          rounding={4}
          color="background-tint-00"
          border="solid"
        >
          <div className="flex flex-col items-stretch gap-4">
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
          </div>
        </Card>
      </div>
    </div>
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
