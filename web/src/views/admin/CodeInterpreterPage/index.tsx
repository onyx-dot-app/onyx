"use client";

import { IconLoader } from "@opal/loaders";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { SettingsLayouts, toast } from "@opal/layouts";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgRefreshCw,
  SvgTerminal,
  SvgUnplug,
  SvgXOctagon,
} from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Section } from "@/layouts/general-layouts";
import { Button, Popover, SelectCard } from "@opal/components";
import { Card, Content, ContentAction } from "@opal/layouts";
import { Hoverable } from "@opal/core";
import Text from "@/refresh-components/texts/Text";
import { ConfirmationModalLayout } from "@opal/layouts";
import useCodeInterpreter, {
  type CodeInterpreterHealthStatus,
} from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/views/admin/CodeInterpreterPage/svc";

const route = ADMIN_ROUTES.CODE_INTERPRETER;

// Message keys, not copy — the literal union keeps `t()` statically checked.
type StatusLabelKey =
  | "status.healthy.label"
  | "status.unhealthy.label"
  | "status.connectionLost.label";

const STATUS_CONFIG: Record<
  CodeInterpreterHealthStatus,
  {
    labelKey: StatusLabelKey;
    icon: typeof SvgCheckCircle;
    color: "success" | "danger";
  }
> = {
  healthy: {
    labelKey: "status.healthy.label",
    icon: SvgCheckCircle,
    color: "success",
  },
  unhealthy: {
    labelKey: "status.unhealthy.label",
    icon: SvgXOctagon,
    color: "danger",
  },
  connection_lost: {
    labelKey: "status.connectionLost.label",
    icon: SvgXOctagon,
    color: "danger",
  },
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CheckingStatus() {
  const t = useTranslations("admin.codeInterpreter");

  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      padding={2}
    >
      <Content
        sizePreset="main-ui"
        variant="body"
        orientation="reverse"
        width="fit"
        icon={IconLoader}
        title={t("status.checking.label")}
        color="muted"
      />
    </Section>
  );
}

interface ConnectionStatusProps {
  status: CodeInterpreterHealthStatus | undefined;
  isLoading: boolean;
  /** Called when the pointer enters or leaves a failed status. */
  onErrorHover: (hovered: boolean) => void;
}

/** The status in the card's corner. A failed status is the trigger of the
 * page's error popover, which opens on hover. */
function ConnectionStatus({
  status,
  isLoading,
  onErrorHover,
}: ConnectionStatusProps) {
  const t = useTranslations("admin.codeInterpreter");

  if (isLoading || !status) {
    return <CheckingStatus />;
  }

  const { labelKey, icon, color } = STATUS_CONFIG[status];
  const statusContent = (
    <Content
      sizePreset="main-ui"
      variant="body"
      orientation="reverse"
      width="fit"
      icon={icon}
      title={t(labelKey)}
      color={color}
    />
  );

  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      padding={2}
    >
      {status === "healthy" ? (
        statusContent
      ) : (
        <Popover.Trigger asChild>
          {/* Keyboard users reach the error details too: focus opens them like
              hover does, and Enter or Space toggles them. */}
          <div
            role="button"
            tabIndex={0}
            className="cursor-pointer rounded-08 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-04"
            // The click toggles the popover; it must not also reconnect.
            onClick={(event) => event.stopPropagation()}
            onMouseEnter={() => onErrorHover(true)}
            onMouseLeave={() => onErrorHover(false)}
            onFocus={() => onErrorHover(true)}
            onBlur={() => onErrorHover(false)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.currentTarget.click();
              }
            }}
          >
            {statusContent}
          </div>
        </Popover.Trigger>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CodeInterpreterPage() {
  const t = useTranslations("admin.codeInterpreter");
  const { status, error, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isErrorOpen, setIsErrorOpen] = useState(false);
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasError = !!status && status !== "healthy";
  const isConnectionLost = status === "connection_lost";

  useEffect(
    () => () => {
      if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
    },
    []
  );

  // The error popover stays open while the pointer is on the status or the
  // popover, and closes a second after it leaves both.
  function handleErrorHover(hovered: boolean) {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
    if (hovered) {
      setIsErrorOpen(true);
      return;
    }
    closeTimeoutRef.current = setTimeout(() => {
      setIsErrorOpen(false);
      closeTimeoutRef.current = null;
    }, 1000);
  }

  // Every card click and the refresh button reconnect: they re-enable the
  // server and check it again.
  async function handleToggle(enabled: boolean) {
    if (enabled && isReconnecting) return;
    setIsReconnecting(enabled);
    try {
      const response = await updateCodeInterpreter({ enabled });
      if (!response.ok) {
        toast.error(
          enabled
            ? t("toggleError.reconnect.message")
            : t("toggleError.disconnect.message")
        );
        return;
      }
      setShowDisconnectModal(false);
      await refetch();
    } finally {
      setIsReconnecting(false);
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("header.title")}
        description={t("header.description")}
        divider
      />

      <SettingsLayouts.Body>
        {isEnabled || isLoading ? (
          <Popover open={hasError && isErrorOpen} onOpenChange={setIsErrorOpen}>
            <Hoverable.Root
              group="code-interpreter/Card"
              interaction={showDisconnectModal ? "hover" : "rest"}
            >
              {/* The error popover opens under the whole card, not the status. */}
              <Popover.Anchor>
                <SelectCard
                  state={isConnectionLost ? "empty" : "filled"}
                  padding={2}
                  rounding={4}
                  onClick={isLoading ? undefined : () => handleToggle(true)}
                >
                  <Card.Header>
                    <ContentAction
                      sizePreset="main-ui"
                      variant="section"
                      icon={SvgTerminal}
                      title={t("card.title")}
                      strikethrough={isConnectionLost}
                      description={t("card.description")}
                      padding={2}
                      rightChildren={
                        <Section alignItems="end" gap={0}>
                          <ConnectionStatus
                            status={status}
                            isLoading={isLoading}
                            onErrorHover={handleErrorHover}
                          />
                          <div className="px-1 pb-1">
                            <Section
                              flexDirection="row"
                              justifyContent="end"
                              gap={1}
                            >
                              <Hoverable.Item group="code-interpreter/Card">
                                <Button
                                  disabled={isLoading}
                                  prominence="tertiary"
                                  size="md"
                                  icon={SvgUnplug}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    setShowDisconnectModal(true);
                                  }}
                                  tooltip={t("card.disconnectButton.tooltip")}
                                />
                              </Hoverable.Item>
                              <Button
                                disabled={isLoading}
                                prominence="tertiary"
                                size="md"
                                icon={
                                  isReconnecting ? IconLoader : SvgRefreshCw
                                }
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleToggle(true);
                                }}
                                tooltip={t("card.refreshButton.tooltip")}
                              />
                            </Section>
                          </div>
                        </Section>
                      }
                    />
                  </Card.Header>
                </SelectCard>
              </Popover.Anchor>
            </Hoverable.Root>
            <Popover.Content
              align="end"
              width={60}
              padding={2}
              gap={2}
              // A hover popover must not take focus from the page.
              onOpenAutoFocus={(event) => event.preventDefault()}
              onCloseAutoFocus={(event) => event.preventDefault()}
              onMouseEnter={() => handleErrorHover(true)}
              onMouseLeave={() => handleErrorHover(false)}
            >
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={SvgXOctagon}
                color="danger"
                titleColor="text-04"
                title={
                  status === "connection_lost"
                    ? t("errorCard.connectionLost.title")
                    : t("errorCard.generic.title")
                }
                description={error}
              />
            </Popover.Content>
          </Popover>
        ) : (
          <SelectCard
            state="empty"
            padding={2}
            rounding={4}
            onClick={() => handleToggle(true)}
          >
            <ContentAction
              sizePreset="main-ui"
              variant="section"
              icon={SvgTerminal}
              title={t("card.disconnectedTitle")}
              description={t("card.description")}
              padding={2}
              rightChildren={
                isReconnecting ? (
                  <CheckingStatus />
                ) : (
                  <Button
                    prominence="tertiary"
                    rightIcon={SvgArrowExchange}
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleToggle(true);
                    }}
                  >
                    {t("card.reconnectButton.label")}
                  </Button>
                )
              }
            />
          </SelectCard>
        )}
      </SettingsLayouts.Body>

      {showDisconnectModal && (
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={t("disconnectModal.header.title")}
          onClose={() => setShowDisconnectModal(false)}
          submit={
            <Button variant="danger" onClick={() => handleToggle(false)}>
              {t("disconnectModal.submitButton.label")}
            </Button>
          }
        >
          <Text as="p" text03>
            {t.rich("disconnectModal.body.description", {
              emphasis: (chunks) => (
                <Text as="span" mainContentEmphasis text03>
                  {chunks}
                </Text>
              ),
            })}
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
