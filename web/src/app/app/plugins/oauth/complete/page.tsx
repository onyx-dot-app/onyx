"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, Card, OnyxLoader } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { SvgConnected, SvgPlugBroken } from "@opal/illustrations";
import { verifyMemberPluginConnection } from "@/lib/plugins/member";
import { notifyMemberPluginOAuthComplete } from "@/lib/plugins/memberConnection";
import { parsePluginId } from "@/lib/plugins/routes";

export default function MemberPluginOAuthCompletePage() {
  const t = useTranslations("actions.memberPlugins.oauthComplete");
  const searchParams = useSearchParams();
  const processed = useRef(false);
  const [status, setStatus] = useState<"checking" | "success" | "error">(
    "checking"
  );

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const kind = searchParams?.get("pluginKind");
    const id = parsePluginId(searchParams?.get("pluginId") ?? undefined);
    const attempt = searchParams?.get("attempt");
    if (
      (kind !== "mcp" && kind !== "openapi" && kind !== "external-app") ||
      id === null ||
      !attempt ||
      searchParams?.get("message") !== "oauth_connected"
    ) {
      setStatus("error");
      return;
    }
    verifyMemberPluginConnection({ kind, id }).then(
      () => {
        notifyMemberPluginOAuthComplete(attempt);
        setStatus("success");
      },
      () => setStatus("error")
    );
  }, [searchParams]);

  return (
    <div className="flex h-full min-h-0 flex-1 items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <Card
          padding={6}
          rounding={4}
          color="background-tint-00"
          border="solid"
        >
          <div className="flex flex-col items-center gap-4">
            {status === "checking" ? (
              <OnyxLoader />
            ) : (
              <IllustrationContent
                illustration={
                  status === "success" ? SvgConnected : SvgPlugBroken
                }
                title={t(`${status}.title`)}
                description={t(`${status}.description`)}
              />
            )}
            <Button href="/app/plugins" width="full">
              {t("return.label")}
            </Button>
            <Button prominence="tertiary" onClick={() => window.close()}>
              {t("close.label")}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
