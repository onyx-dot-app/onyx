"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Card, Text } from "@opal/components";
import { SvgUnplug } from "@opal/icons";
import {
  ConfirmationModalLayout,
  Content,
  Section,
  toast,
} from "@opal/layouts";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { useUser } from "@/providers/UserProvider";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { OAuthProviderGrant } from "@/lib/oauth-provider/types";

export default function OAuthProviderConnections() {
  const t = useTranslations("mcpOAuth");
  const format = useFormatter();
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const enabled = useSettings().oauth_provider_enabled;
  const { user } = useUser();
  const [selected, setSelected] = useState<OAuthProviderGrant | null>(null);
  const [revoking, setRevoking] = useState(false);
  const { data, error, isLoading, mutate } = useSWR<
    OAuthProviderGrant[],
    FetchError
  >(
    enabled && user ? [SWR_KEYS.oauthProviderGrants, user.id] : null,
    ([url]: [string, string]) =>
      errorHandlingFetcher<OAuthProviderGrant[]>(url),
    { shouldRetryOnError: false }
  );

  async function disconnect() {
    if (!selected || revoking) return;
    setRevoking(true);
    try {
      const response = await fetch(
        `/api/oauth-provider/grants/${encodeURIComponent(selected.id)}`,
        { method: "DELETE" }
      );
      if (!response.ok) throw new Error("OAuth provider disconnect failed");
      setSelected(null);
      await mutate();
    } catch {
      toast.error(t("connections.failed"));
    } finally {
      setRevoking(false);
    }
  }

  if (!enabled || !user) return null;

  return (
    <Section gap={3} height="fit" alignItems="stretch">
      <Content
        title={t("connections.title")}
        description={t("connections.description")}
        sizePreset="main-content"
        variant="section"
        width="full"
      />
      <Card border="solid" rounding={4}>
        <Section height="fit" alignItems="stretch">
          {error ? (
            <Text font="main-ui-body" color="text-04" role="alert">
              {t("connections.loadFailed")}
            </Text>
          ) : isLoading ? (
            <Text font="main-ui-body" color="text-04" role="status">
              {t("connections.loading")}
            </Text>
          ) : !data?.length ? (
            <Text font="main-ui-body" color="text-03">
              {t("connections.empty")}
            </Text>
          ) : (
            data.map((grant) => (
              <Section
                key={grant.id}
                flexDirection="row"
                justifyContent="between"
                alignItems="center"
                height="fit"
                wrap
              >
                <Section width="auto" height="fit" alignItems="start" gap={1}>
                  <Text
                    font="main-content-emphasis"
                    color="text-05"
                    wordWrap="wrap-anywhere"
                  >
                    {grant.client_name}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {t("connections.expires", {
                      date: format.dateTime(new Date(grant.expires_at), {
                        dateStyle: "medium",
                        timeZone,
                      }),
                    })}
                  </Text>
                </Section>
                <Button
                  prominence="secondary"
                  icon={SvgUnplug}
                  aria-label={t("connections.disconnectAriaLabel", {
                    clientName: grant.client_name,
                  })}
                  disabled={revoking}
                  onClick={() => setSelected(grant)}
                >
                  {t("connections.disconnect")}
                </Button>
              </Section>
            ))
          )}
        </Section>
      </Card>
      {selected && (
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={t("connections.confirmTitle", {
            clientName: selected.client_name,
          })}
          hideCancel
          onClose={() => setSelected(null)}
          submit={
            <>
              <Button
                prominence="secondary"
                disabled={revoking}
                onClick={() => setSelected(null)}
              >
                {t("connections.cancel")}
              </Button>
              <Button
                variant="danger"
                disabled={revoking}
                onClick={() => void disconnect()}
              >
                {revoking
                  ? t("connections.pending")
                  : t("connections.disconnect")}
              </Button>
            </>
          }
        >
          <Text font="main-ui-body" color="text-04">
            {t("connections.confirmDescription")}
          </Text>
        </ConfirmationModalLayout>
      )}
    </Section>
  );
}
