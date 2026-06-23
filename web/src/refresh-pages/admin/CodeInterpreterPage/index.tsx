"use client";

import { useState } from "react";
import { SettingsLayouts } from "@opal/layouts";
import { useTranslation } from "react-i18next";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgRefreshCw,
  SvgTerminal,
  SvgUnplug,
  SvgXOctagon,
  SvgSimpleLoader,
} from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminPageTitle } from "@/lib/admin-i18n";
import { Section } from "@/layouts/general-layouts";
import { Button, SelectCard } from "@opal/components";
import { Card, Content, ContentAction } from "@opal/layouts";
import { Disabled, Hoverable } from "@opal/core";
import Text from "@/refresh-components/texts/Text";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import useCodeInterpreter from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/refresh-pages/admin/CodeInterpreterPage/svc";
import { toast } from "@/hooks/useToast";
import { cn } from "@opal/utils";

const route = ADMIN_ROUTES.CODE_INTERPRETER;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CheckingStatus() {
  const { t } = useTranslation();

  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      gap={0.25}
      padding={0.5}
    >
      <Text mainUiAction text03>
        {t("admin.common.checking")}
      </Text>
      <SvgSimpleLoader />
    </Section>
  );
}

interface ConnectionStatusProps {
  healthy: boolean;
  isLoading: boolean;
}

function ConnectionStatus({ healthy, isLoading }: ConnectionStatusProps) {
  const { t } = useTranslation();

  if (isLoading) {
    return <CheckingStatus />;
  }

  const label = healthy
    ? t("admin.common.connected")
    : t("admin.common.connection_lost");
  const Icon = healthy ? SvgCheckCircle : SvgXOctagon;
  const iconColor = healthy
    ? "text-status-success-05!"
    : "text-status-error-05!";

  return (
    <div className="p-2">
      <Content
        title={label}
        icon={(props) => (
          <Icon {...props} className={cn(props.className, iconColor)} />
        )}
        sizePreset="main-ui"
        variant="body"
        orientation="reverse"
        color="muted"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CodeInterpreterPage() {
  const { t } = useTranslation();
  const title = useAdminPageTitle(route);
  const { isHealthy, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);

  async function handleToggle(enabled: boolean) {
    setIsReconnecting(enabled);
    try {
      const response = await updateCodeInterpreter({ enabled });
      if (!response.ok) {
        toast.error(
          enabled
            ? t("admin.code_interpreter.reconnect_failed")
            : t("admin.code_interpreter.disconnect_failed")
        );
        return;
      }
      setShowDisconnectModal(false);
      refetch();
    } finally {
      setIsReconnecting(false);
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={title}
        description={t("admin.code_interpreter.description")}
        divider
      />

      <SettingsLayouts.Body>
        {isEnabled || isLoading ? (
          <Hoverable.Root
            group="code-interpreter/Card"
            interaction={showDisconnectModal ? "hover" : "rest"}
          >
            <SelectCard state="filled" padding="sm" rounding="lg">
              <Card.Header>
                <ContentAction
                  sizePreset="main-ui"
                  variant="section"
                  icon={SvgTerminal}
                  title={t("admin.code_interpreter.title")}
                  description={t("admin.code_interpreter.subtitle")}
                  padding="lg"
                  rightChildren={
                    <Section alignItems="end" gap={0}>
                      <ConnectionStatus
                        healthy={isHealthy}
                        isLoading={isLoading}
                      />
                      <div className="px-1 pb-1">
                        <Section
                          flexDirection="row"
                          justifyContent="end"
                          gap={0.25}
                        >
                          <Disabled disabled={isLoading}>
                            <Hoverable.Item group="code-interpreter/Card">
                              <Button
                                prominence="tertiary"
                                size="md"
                                icon={SvgUnplug}
                                onClick={() => setShowDisconnectModal(true)}
                                tooltip={t("admin.code_interpreter.disconnect_tooltip")}
                              />
                            </Hoverable.Item>
                          </Disabled>
                          <Button
                            disabled={isLoading}
                            prominence="tertiary"
                            size="md"
                            icon={SvgRefreshCw}
                            onClick={refetch}
                            tooltip={t("admin.common.refresh")}
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
            padding="sm"
            rounding="lg"
            onClick={() => handleToggle(true)}
          >
            <ContentAction
              sizePreset="main-ui"
              variant="section"
              icon={SvgTerminal}
              title={t("admin.code_interpreter.disconnected_title")}
              description={t("admin.code_interpreter.subtitle")}
              padding="lg"
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
                    {t("admin.common.reconnect")}
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
          title={t("admin.code_interpreter.disconnect_modal_title")}
          onClose={() => setShowDisconnectModal(false)}
          submit={
            <Button variant="danger" onClick={() => handleToggle(false)}>
              {t("admin.common.disconnect")}
            </Button>
          }
        >
          <Text as="p" text03>
            {t("admin.code_interpreter.disconnect_modal_desc")}
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
