"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgKey } from "@opal/icons";
import { useSWRConfig } from "swr";
import { connectAction, needsAdmin } from "@/lib/integrations/connect";
import { useIntegrationConnect } from "@/lib/integrations/hooks";
import { deleteUserConnection } from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import IntegrationCredentialsModal from "@/sections/plugins/IntegrationCredentialsModal";

interface IntegrationConnectButtonProps {
  integration: MemberIntegration;
  /** Where the OAuth callback returns when no waiting tab closes it. */
  returnPath: string;
  allowDisconnect?: boolean;
  /** False: no Connect or Reconnect, and a broken connection offers Disconnect. */
  allowConnect?: boolean;
  onConnected?: () => void;
  /** Called when a connect attempt fails or is abandoned. */
  onConnectFailed?: () => void;
  /** Called before a blocked popup moves the sign-in to this tab. */
  onRedirect?: () => void;
}

/** Connect, Reconnect, Disconnect or "Ask your admin" for one integration. */
export default function IntegrationConnectButton({
  integration,
  returnPath,
  allowDisconnect = false,
  allowConnect = true,
  onConnected,
  onConnectFailed,
  onRedirect,
}: IntegrationConnectButtonProps) {
  const t = useTranslations("plugins.member.connection");
  const { mutate } = useSWRConfig();
  const [disconnecting, setDisconnecting] = useState(false);
  const connectRef = useRef<HTMLSpanElement>(null);
  const signIn = useIntegrationConnect(integration, {
    returnPath,
    onConnected,
    onRedirect,
    onConnectFailed: () => {
      onConnectFailed?.();
      window.requestAnimationFrame(() =>
        connectRef.current?.querySelector("button")?.focus()
      );
    },
  });
  const busy = signIn.busy || disconnecting;
  const { state } = integration.status;
  const action = allowConnect ? connectAction(integration) : null;
  const askAdmin = !action && allowConnect && needsAdmin(integration);
  // A broken connection offers Disconnect beside Reconnect.
  const canDisconnect =
    !askAdmin &&
    (state === "connected" || state === "needs_reconnect") &&
    allowDisconnect &&
    integration.auth_mode === "individual";
  const name = integration.name;

  async function disconnect() {
    setDisconnecting(true);
    try {
      await deleteUserConnection(integration.id);
      toast.success(t("disconnected", { name }));
      await mutate(SWR_KEYS.integrations);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("disconnectFailed")
      );
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <>
      {action ? (
        <span ref={connectRef} className="contents">
          <Button
            key="connect"
            size="md"
            prominence={action === "reconnect" ? "primary" : "secondary"}
            icon={signIn.busy ? IconLoader : SvgKey}
            disabled={busy}
            aria-label={t(`${action}.ariaLabel`, { name })}
            onClick={(event) => {
              event.stopPropagation();
              void signIn.connect();
            }}
          >
            {t(`${action}.label`)}
          </Button>
        </span>
      ) : askAdmin ? (
        <Text font="secondary-body" color="text-03">
          {t("askAdmin")}
        </Text>
      ) : null}
      {canDisconnect && (
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
      )}
      {signIn.credentialsOpen && (
        <IntegrationCredentialsModal
          integration={integration}
          onClose={signIn.closeCredentials}
          onConnected={signIn.credentialsConnected}
        />
      )}
    </>
  );
}
