"use client";

import { useTranslations } from "next-intl";
import { Button, MessageCard, Text } from "@opal/components";
import { useOAuthConnectionTest } from "@/lib/oauth/hooks";
import { oauthTestRequest } from "@/lib/oauth/testConnection";
import type { OAuthConfigFields } from "@/lib/oauth/config";

interface OAuthConnectionCheckProps {
  values: OAuthConfigFields;
  configId?: number | null;
  disabled?: boolean;
}

export default function OAuthConnectionCheck({
  values,
  configId,
  disabled,
}: OAuthConnectionCheckProps) {
  const t = useTranslations("actions.openApiAuthModal.connectionCheck");
  const { result, start } = useOAuthConnectionTest(
    oauthTestRequest(values, configId)
  );
  return (
    <div className="flex flex-col gap-3">
      <Text as="p" font="secondary-body" color="text-03">
        {t("description")}
      </Text>
      <div>
        <Button
          prominence="secondary"
          disabled={disabled || result.status === "pending"}
          onClick={start}
        >
          {t(result.status === "pending" ? "testing" : "test")}
        </Button>
      </div>
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
