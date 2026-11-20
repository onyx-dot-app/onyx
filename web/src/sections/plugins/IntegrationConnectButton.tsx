"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgKey } from "@opal/icons";
import { useSWRConfig } from "swr";
import {
  connectAction,
  connectWithOAuth,
  needsAdmin,
} from "@/lib/integrations/connect";
import { deleteUserConnection, startUserOAuth } from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";
import { isSilentOAuthOutcome, oauthFailureDetail } from "@/lib/oauth/launch";
import { SWR_KEYS } from "@/lib/swr-keys";
import IntegrationCredentialsModal from "@/sections/plugins/IntegrationCredentialsModal";

interface IntegrationConnectButtonProps {
  integration: MemberIntegration;
  /** Where the OAuth callback returns when no waiting tab closes it. */
  returnPath: string;
  allowDisconnect?: boolean;
  onConnected?: () => void;
}

/** Connect, Reconnect, Disconnect or "Ask your admin" for one integration. */
export default function IntegrationConnectButton({
  integration,
  returnPath,
  allowDisconnect = false,
  onConnected,
}: IntegrationConnectButtonProps) {
  const t = useTranslations("plugins.member.connection");
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const { state } = integration.status;
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
      const result = await connectWithOAuth(
        (path) => startUserOAuth(integration.id, path),
        returnPath
      );
      if (result === "connected") await connected();
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

  return (
    <>
      {action ? (
        <Button
          key="connect"
          size="md"
          prominence={action === "reconnect" ? "primary" : "secondary"}
          icon={busy ? IconLoader : SvgKey}
          disabled={busy}
          aria-label={t(`${action}.ariaLabel`, { name })}
          onClick={(event) => {
            event.stopPropagation();
            void connect();
          }}
        >
          {t(`${action}.label`)}
        </Button>
      ) : needsAdmin(integration) ? (
        <Text font="secondary-body" color="text-03">
          {t("askAdmin")}
        </Text>
      ) : state === "connected" &&
        allowDisconnect &&
        integration.auth_mode === "individual" ? (
        <Button
          key="disconnect"
          size="md"
          prominence="secondary"
          disabled={busy}
          aria-label={t("disconnect.ariaLabel", { name })}
          onClick={(event) => {
            event.stopPropagation();
            void disconnect();
          }}
        >
          {t("disconnect.label")}
        </Button>
      ) : null}
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
