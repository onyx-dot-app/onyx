"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Modal, Text } from "@opal/components";
import { SvgCheck, SvgKey, SvgServer } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import type { MinimalAgent } from "@/lib/agents/types";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { useMcpAuthentication } from "@/lib/mcp/hooks";
import { getMcpAuthenticationFlow } from "@/lib/mcp/auth";
import { MCPConnectionStatus } from "@/lib/mcp/types";
import { MCPUserCredentialsContent } from "@/lib/mcp/components/MCPUserCredentialsModal";

interface MCPConnectionPromptProps {
  agent: Pick<MinimalAgent, "id" | "tools">;
  toolConfiguration: Pick<ToolConfigurationHandle, "disabledToolIds" | "ready">;
  disabled?: boolean;
  isStreaming?: boolean;
  onConnectionsClosed?: () => void;
}

function WarningKey({ className, ...props }: IconProps) {
  return (
    <SvgKey {...props} className={cn(className, "stroke-status-warning-05")} />
  );
}

function ConnectionKey({ className, ...props }: IconProps) {
  return (
    <SvgKey {...props} className={cn(className, "stroke-status-info-05")} />
  );
}

export default function MCPConnectionPrompt({
  agent,
  toolConfiguration,
  disabled = false,
  isStreaming = false,
  onConnectionsClosed,
}: MCPConnectionPromptProps) {
  const t = useTranslations("chat.mcpConnections");
  const [open, setOpen] = useState(false);
  const [openedServerIds, setOpenedServerIds] = useState<number[]>([]);
  const navigatingToCredentials = useRef(false);
  const wasStreaming = useRef(isStreaming);
  const triggerRef = useRef<HTMLElement>(null);
  const {
    servers,
    refresh,
    authenticate,
    loadingServerId,
    authenticationError,
    credentialRequest,
    cancelCredentialRequest,
    submitCredentials,
  } = useMcpAuthentication(agent.id);

  useEffect(() => {
    if (wasStreaming.current && !isStreaming) void refresh();
    wasStreaming.current = isStreaming;
  }, [isStreaming, refresh]);

  const pendingServers = servers.filter((server) => {
    const status = server.connection_status;
    return (
      (status === MCPConnectionStatus.NOT_CONNECTED ||
        status === MCPConnectionStatus.REAUTH_REQUIRED) &&
      getMcpAuthenticationFlow(server) !== null &&
      agent.tools.some(
        (tool) =>
          tool.mcp_server_id === server.id &&
          tool.enabled &&
          !toolConfiguration.disabledToolIds.includes(tool.id)
      )
    );
  });
  const needsReauthentication = pendingServers.some(
    (server) => server.connection_status === MCPConnectionStatus.REAUTH_REQUIRED
  );
  const visibleServers = servers.filter((server) =>
    openedServerIds.includes(server.id)
  );

  function openConnections() {
    setOpenedServerIds(pendingServers.map((server) => server.id));
    setOpen(true);
  }

  return (
    <>
      {pendingServers.length > 0 && toolConfiguration.ready && (
        <div className="ps-1">
          <div
            className={cn(
              "rounded-08 transition-colors",
              needsReauthentication
                ? "bg-status-warning-00"
                : "bg-status-info-00",
              disabled
                ? "opacity-50"
                : needsReauthentication
                  ? "hover:bg-status-warning-01"
                  : "hover:bg-status-info-01"
            )}
          >
            <Button
              ref={triggerRef}
              icon={needsReauthentication ? WarningKey : ConnectionKey}
              variant="default"
              prominence="tertiary"
              size="md"
              responsiveHideText
              tooltip={open ? undefined : t("trigger.tooltip")}
              aria-label={t("trigger.label", { count: pendingServers.length })}
              disabled={disabled}
              onClick={openConnections}
              aria-haspopup="dialog"
            >
              {t("trigger.label", { count: pendingServers.length })}
            </Button>
          </div>
        </div>
      )}
      <Modal
        open={open}
        onOpenChange={(nextOpen) => {
          // The credential page guards every close, including Dialog.Close.
          if (!credentialRequest) setOpen(nextOpen);
        }}
      >
        <Modal.Backdrop />
        {credentialRequest ? (
          <MCPUserCredentialsContent
            key={credentialRequest.server.id}
            server={credentialRequest.server}
            skipOverlay
            onSubmit={async (credentials) => {
              await submitCredentials(credentials);
              navigatingToCredentials.current = false;
            }}
            onBack={() => {
              navigatingToCredentials.current = false;
              cancelCredentialRequest();
            }}
            onDismissFocus={() => {
              if (triggerRef.current) triggerRef.current.focus();
              else onConnectionsClosed?.();
            }}
            onClose={() => {
              navigatingToCredentials.current = false;
              cancelCredentialRequest();
              setOpen(false);
            }}
          />
        ) : (
          <Modal.Content
            width="sm"
            skipOverlay
            onCloseAutoFocus={(event) => {
              if (navigatingToCredentials.current) {
                event.preventDefault();
                return;
              }
              if (triggerRef.current) {
                event.preventDefault();
                triggerRef.current.focus();
              } else if (onConnectionsClosed) {
                event.preventDefault();
                onConnectionsClosed();
              }
            }}
          >
            <Modal.Header
              icon={SvgKey}
              title={t("modal.title")}
              description={t("modal.description")}
              onClose={() => setOpen(false)}
            />
            <Modal.Body gap={3}>
              <div className="flex w-full flex-col gap-2">
                {visibleServers.map((server) => {
                  const status = server.connection_status;
                  const connected = status === MCPConnectionStatus.CONNECTED;
                  const reconnect =
                    status === MCPConnectionStatus.REAUTH_REQUIRED;
                  const connecting = loadingServerId === server.id;
                  return (
                    <div
                      key={server.id}
                      className="w-full rounded-12 border border-border-01 bg-background-neutral-00 p-2"
                    >
                      <ContentAction
                        icon={connected ? SvgCheck : SvgServer}
                        color={connected ? "success" : "default"}
                        title={server.name}
                        description={
                          connected ? t("connected.label") : undefined
                        }
                        sizePreset="main-ui"
                        variant="section"
                        padding={2}
                        rightChildren={
                          !connected && (
                            <div className="flex items-center pe-1">
                              <Button
                                prominence="primary"
                                size="md"
                                icon={connecting ? IconLoader : SvgKey}
                                disabled={loadingServerId !== null}
                                aria-label={t(
                                  reconnect
                                    ? "reconnect.accessibleLabel"
                                    : "connect.accessibleLabel",
                                  {
                                    server: server.name,
                                  }
                                )}
                                onClick={() => {
                                  navigatingToCredentials.current =
                                    getMcpAuthenticationFlow(server) ===
                                    "credentials";
                                  void authenticate(server);
                                }}
                              >
                                {t(
                                  connecting
                                    ? "connecting.label"
                                    : reconnect
                                      ? "reconnect.label"
                                      : "connect.label"
                                )}
                              </Button>
                            </div>
                          )
                        }
                      />
                    </div>
                  );
                })}
                {authenticationError && (
                  <div role="alert">
                    <Text font="main-ui-body" color="text-04">
                      {t("error.description")}
                    </Text>
                  </div>
                )}
              </div>
              <Text font="secondary-body" color="text-03">
                {t("modal.hint")}
              </Text>
            </Modal.Body>
            <Modal.Footer>
              <Button prominence="secondary" onClick={() => setOpen(false)}>
                {t("done.label")}
              </Button>
            </Modal.Footer>
          </Modal.Content>
        )}
      </Modal>
    </>
  );
}
