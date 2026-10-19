"use client";

import { useTranslations } from "next-intl";
import { Button, MessageCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgPlay } from "@opal/icons";
import { useOAuthConnectionTest } from "@/lib/oauth/hooks";
import { oauthConfigRequest, type OAuthConfigFields } from "@/lib/oauth/config";

interface OAuthConnectionCheckProps {
  values: OAuthConfigFields;
  configId?: number | null;
  disabled?: boolean;
}

/**
 * Runs a test authorization with the unsaved OAuth settings. The button
 * label stays fixed; its icon turns into a spinner while the check runs.
 */
export default function OAuthConnectionCheck({
  values,
  configId,
  disabled,
}: OAuthConnectionCheckProps) {
  const t = useTranslations("actions.openApiAuthModal.connectionCheck");
  const config = oauthConfigRequest(values, Boolean(configId));
  const { result, start } = useOAuthConnectionTest({
    ...config,
    oauth_config_id: configId ?? undefined,
    client_id: config.client_id || undefined,
    client_secret: config.client_secret || undefined,
  });
  const pending = result.status === "pending";
  return (
    <div className="flex flex-col gap-3">
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        padding={0}
        title={t("title")}
        description={t("description")}
        rightChildren={
          <Button
            prominence="secondary"
            icon={pending ? IconLoader : SvgPlay}
            disabled={disabled || pending}
            onClick={start}
          >
            {t("start")}
          </Button>
        }
      />
      {result.status !== "idle" && result.status !== "pending" && (
        <div role="status" aria-live="polite">
          <MessageCard
            outerPadding={1}
            innerPadding={1}
            variant={
              result.status === "success"
                ? "success"
                : result.status === "stale"
                  ? "info"
                  : "warning"
            }
            title={
              result.status === "success"
                ? t(result.supports_pkce ? "successPkce" : "success")
                : t(`result.${result.status}`)
            }
          />
        </div>
      )}
    </div>
  );
}
