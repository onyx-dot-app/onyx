"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { ContentAction, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgCheckCircle, SvgKey, SvgPlug } from "@opal/icons";
import { useSWRConfig } from "swr";
import { connectAction, connectWithOAuth } from "@/lib/integrations/connect";
import { deleteUserConnection } from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";
import { isSilentOAuthOutcome, oauthFailureDetail } from "@/lib/oauth/launch";
import { SWR_KEYS } from "@/lib/swr-keys";
import IntegrationCredentialsModal from "@/sections/plugins/IntegrationCredentialsModal";

interface IntegrationConnectionRowProps {
  integration: MemberIntegration;
  /** Where the OAuth callback returns when no waiting tab closes it. */
  returnPath: string;
  /** Shows Disconnect on a connection of the user's own. */
  allowDisconnect?: boolean;
  onConnected?: () => void;
}

/** One integration with its status: Connected, Not connected, Needs
 * reconnect or Not set up, and the action that fixes it. */
export default function IntegrationConnectionRow({
  integration,
  returnPath,
  allowDisconnect = false,
  onConnected,
}: IntegrationConnectionRowProps) {
  const t = useTranslations("plugins.member.connection");
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const { state, reason, moving_credentials } = integration.status;
  const action = connectAction(integration);
  const name = integration.name;

  async function refresh() {
    await mutate(SWR_KEYS.integrations);
  }

  async function connected() {
    toast.success(t("connected", { name }));
    await refresh();
    onConnected?.();
  }

  async function connect() {
    if (integration.auth_method === "api_key") {
      setCredentialsOpen(true);
      return;
    }
    setBusy(true);
    try {
      if ((await connectWithOAuth(integration.id, returnPath)) === "connected")
        await connected();
    } catch (error) {
      if (!isSilentOAuthOutcome(error))
        toast.error(
          oauthFailureDetail(error)?.description ??
            (error instanceof Error && error.message
              ? error.message
              : t("failed"))
        );
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await deleteUserConnection(integration.id);
      toast.success(t("disconnected", { name }));
      await refresh();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("disconnectFailed")
      );
    } finally {
      setBusy(false);
    }
  }

  const description = moving_credentials
    ? t("movingCredentials")
    : state === "connected"
      ? t("status.connected")
      : state === "not_connected"
        ? t("status.notConnected")
        : state === "needs_reconnect"
          ? (reason ?? t("status.needsReconnect"))
          : t("status.notSetUp");

  return (
    <>
      <ContentAction
        icon={state === "connected" ? SvgCheckCircle : SvgPlug}
        color={state === "connected" ? "success" : "default"}
        title={name}
        description={description}
        padding={2}
        rightChildren={
          action ? (
            <Button
              size="md"
              icon={busy ? IconLoader : SvgKey}
              disabled={busy}
              aria-label={t(`${action}Label`, { name })}
              onClick={() => void connect()}
            >
              {t(action)}
            </Button>
          ) : state === "not_set_up" ? (
            <Text font="secondary-body" color="text-03">
              {t("askAdmin")}
            </Text>
          ) : state === "connected" &&
            allowDisconnect &&
            integration.auth_mode === "individual" ? (
            <Button
              size="md"
              prominence="secondary"
              disabled={busy}
              aria-label={t("disconnectLabel", { name })}
              onClick={() => void disconnect()}
            >
              {t("disconnect")}
            </Button>
          ) : undefined
        }
      />
      {credentialsOpen && (
        <IntegrationCredentialsModal
          integration={integration}
          onClose={() => setCredentialsOpen(false)}
          onConnected={() => {
            setCredentialsOpen(false);
            void connected();
          }}
        />
      )}
    </>
  );
}
