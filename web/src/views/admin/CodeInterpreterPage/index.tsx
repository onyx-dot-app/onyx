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
import { Disabled, Hoverable } from "@opal/core";
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
      gap={1}
      padding={2}
    >
      <Text mainUiAction text03>
        {t("status.checking.label")}
      </Text>
      <IconLoader />
    </Section>
  );
}

interface ConnectionStatusProps {
  status: CodeInterpreterHealthStatus | undefined;
  error: string | undefined;
  isLoading: boolean;
}

function ConnectionStatus({ status, error, isLoading }: ConnectionStatusProps) {
  const t = useTranslations("admin.codeInterpreter");
  const [isErrorOpen, setIsErrorOpen] = useState(false);
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
    },
    []
  );

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

  // The error card stays open while the pointer is on the status or the card,
  // and closes a second after it leaves both.
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
        <Popover open={isErrorOpen} onOpenChange={setIsErrorOpen}>
          <Popover.Trigger asChild>
            <div
              className="cursor-pointer"
              onMouseEnter={() => handleErrorHover(true)}
              onMouseLeave={() => handleErrorHover(false)}
            >
              {statusContent}
            </div>
          </Popover.Trigger>
          <Popover.Content
            align="end"
            width="md"
            onMouseEnter={() => handleErrorHover(true)}
            onMouseLeave={() => handleErrorHover(false)}
          >
            <Section padding={1}>
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={SvgXOctagon}
                color="danger"
                title={
                  status === "connection_lost"
                    ? t("errorCard.connectionLost.title")
                    : t("errorCard.generic.title")
                }
                description={error}
              />
            </Section>
          </Popover.Content>
        </Popover>
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

  async function handleToggle(enabled: boolean) {
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
      refetch();
    } finally {
      setIsReconnecting(false);
    }
  }

  useEffect(() => {
    return () => {
      if (fadeTimeoutRef.current) {
        clearTimeout(fadeTimeoutRef.current);
      }
    };
  }, []);

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
          <Hoverable.Root
            group="code-interpreter/Card"
            interaction={showDisconnectModal ? "hover" : "rest"}
          >
            <SelectCard state="filled" padding={2} rounding={4}>
              <Card.Header>
                <ContentAction
                  sizePreset="main-ui"
                  variant="section"
                  icon={SvgTerminal}
                  title={t("card.title")}
                  description={t("card.description")}
                  padding={2}
                  rightChildren={
                    <Section alignItems="end" gap={0}>
                      <ConnectionStatus
                        status={status}
                        error={error}
                        isLoading={isLoading}
                      />
                      <div className="px-1 pb-1">
                        <Section
                          flexDirection="row"
                          justifyContent="end"
                          gap={1}
                        >
                          <Disabled disabled={isLoading}>
                            <Hoverable.Item group="code-interpreter/Card">
                              <Button
                                prominence="tertiary"
                                size="md"
                                icon={SvgUnplug}
                                onClick={() => setShowDisconnectModal(true)}
                                tooltip={t("card.disconnectButton.tooltip")}
                              />
                            </Hoverable.Item>
                          </Disabled>
                          <Button
                            disabled={isLoading}
                            prominence="tertiary"
                            size="md"
                            icon={SvgRefreshCw}
                            onClick={refetch}
                            tooltip={t("card.refreshButton.tooltip")}
                          />
                        </Section>
                      </div>
                    </Section>
                  }
                />
              </Card.Header>
            </SelectCard>
          </Hoverable.Root>
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
                      handleToggle(true);
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
