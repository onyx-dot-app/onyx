"use client";

import React, { useEffect, useRef, useState } from "react";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Card, type CardProps } from "@/refresh-components/cards";
import {
  SvgAlertCircle,
  SvgArrowExchange,
  SvgCheckCircle,
  SvgRefreshCw,
  SvgTerminal,
  SvgUnplug,
  SvgXOctagon,
} from "@opal/icons";
import { ADMIN_ROUTE_CONFIG, ADMIN_PATHS } from "@/lib/admin-routes";
import { Section } from "@/layouts/general-layouts";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import useCodeInterpreter, {
  type CodeInterpreterHealthStatus,
} from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/lib/admin/code-interpreter/svc";
import { Content, ContentAction } from "@opal/layouts";
import { toast } from "@/hooks/useToast";

const route = ADMIN_ROUTE_CONFIG[ADMIN_PATHS.CODE_INTERPRETER]!;

interface CodeInterpreterCardProps {
  variant?: CardProps["variant"];
  title: string;
  middleText?: string;
  strikethrough?: boolean;
  rightContent: React.ReactNode;
}

function CodeInterpreterCard({
  variant,
  title,
  middleText,
  strikethrough,
  rightContent,
}: CodeInterpreterCardProps) {
  return (
    // TODO (@raunakab): Allow Content to accept strikethrough and middleText
    <Card variant={variant} padding={0.5}>
      <ContentAction
        icon={SvgTerminal}
        title={middleText ? `${title} ${middleText}` : title}
        description="Built-in Python runtime"
        variant="section"
        sizePreset="main-ui"
        rightChildren={rightContent}
      />
    </Card>
  );
}

function CheckingStatus() {
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      gap={0.25}
      padding={0.5}
    >
      <Text mainUiAction text03>
        Checking...
      </Text>
      <SimpleLoader />
    </Section>
  );
}

const STATUS_CONFIG: Record<
  CodeInterpreterHealthStatus,
  { label: string; icon: typeof SvgCheckCircle; iconColor: string }
> = {
  healthy: {
    label: "Connected",
    icon: SvgCheckCircle,
    iconColor: "text-status-success-05",
  },
  unhealthy: {
    label: "Unhealthy",
    icon: SvgAlertCircle,
    iconColor: "text-status-warning-05",
  },
  connection_lost: {
    label: "Connection Lost",
    icon: SvgXOctagon,
    iconColor: "text-status-error-05",
  },
};

interface ConnectionStatusProps {
  status: CodeInterpreterHealthStatus | undefined;
  isLoading: boolean;
  onIconHover: (hovered: boolean) => void;
}

function ConnectionStatus({
  status,
  isLoading,
  onIconHover,
}: ConnectionStatusProps) {
  if (isLoading) {
    return <CheckingStatus />;
  }

  const { label, icon: Icon, iconColor } = STATUS_CONFIG[status!];
  const hasError = status !== "healthy";

  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      gap={0.25}
      padding={0.5}
    >
      <Text mainUiAction text03>
        {label}
      </Text>
      <div
        onMouseEnter={() => hasError && onIconHover(true)}
        onMouseLeave={() => onIconHover(false)}
        className={hasError ? "cursor-pointer" : undefined}
      >
        <Icon size={16} className={iconColor} />
      </div>
    </Section>
  );
}

interface ActionButtonsProps {
  onDisconnect: () => void;
  onRefresh: () => void;
  disabled?: boolean;
}

function ActionButtons({
  onDisconnect,
  onRefresh,
  disabled,
}: ActionButtonsProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      gap={0.25}
      padding={0.25}
    >
      <Disabled disabled={disabled}>
        <Button
          prominence="tertiary"
          size="sm"
          icon={SvgUnplug}
          onClick={onDisconnect}
          tooltip="Disconnect"
        />
      </Disabled>
      <Disabled disabled={disabled}>
        <Button
          prominence="tertiary"
          size="sm"
          icon={SvgRefreshCw}
          onClick={onRefresh}
          tooltip="Refresh"
        />
      </Disabled>
    </Section>
  );
}

export default function CodeInterpreterPage() {
  const { status, error, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const isHealthy = status === "healthy";
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [showErrorMenu, setShowErrorMenu] = useState(false);
  const fadeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleErrorHover(hovered: boolean) {
    if (hovered) {
      if (fadeTimeoutRef.current) {
        clearTimeout(fadeTimeoutRef.current);
        fadeTimeoutRef.current = null;
      }
      setShowErrorMenu(true);
    } else {
      if (fadeTimeoutRef.current) {
        clearTimeout(fadeTimeoutRef.current);
      }
      fadeTimeoutRef.current = setTimeout(() => {
        setShowErrorMenu(false);
        fadeTimeoutRef.current = null;
      }, 1000);
    }
  }

  async function handleToggle(enabled: boolean) {
    const action = enabled ? "reconnect" : "disconnect";
    setIsReconnecting(enabled);
    try {
      const response = await updateCodeInterpreter({ enabled });
      if (!response.ok) {
        toast.error(`Failed to ${action} Code Interpreter`);
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
        title={route.title}
        description="Safe and sandboxed Python runtime available to your LLM. See docs for more details."
        separator
      />

      <SettingsLayouts.Body>
        <Section flexDirection="column" padding={0} gap={0.2}>
          {isEnabled || isLoading ? (
            <CodeInterpreterCard
              title="Code Interpreter"
              variant={isHealthy ? "primary" : "secondary"}
              strikethrough={!isHealthy}
              rightContent={
                <Section
                  flexDirection="column"
                  justifyContent="center"
                  alignItems="end"
                  gap={0}
                  padding={0}
                >
                  <ConnectionStatus
                    status={status}
                    isLoading={isLoading}
                    onIconHover={handleErrorHover}
                  />
                  <ActionButtons
                    onDisconnect={() => setShowDisconnectModal(true)}
                    onRefresh={refetch}
                    disabled={isLoading}
                  />
                </Section>
              }
            />
          ) : (
            <CodeInterpreterCard
              variant="secondary"
              title="Code Interpreter"
              middleText="(Disconnected)"
              strikethrough={true}
              rightContent={
                <Section flexDirection="row" alignItems="center" padding={0.5}>
                  {isReconnecting ? (
                    <CheckingStatus />
                  ) : (
                    <Button
                      prominence="tertiary"
                      rightIcon={SvgArrowExchange}
                      onClick={() => handleToggle(true)}
                    >
                      Reconnect
                    </Button>
                  )}
                </Section>
              }
            />
          )}
          {showErrorMenu && (
            <Section
              flexDirection="row"
              justifyContent="end"
              onMouseEnter={() => handleErrorHover(true)}
              onMouseLeave={() => handleErrorHover(false)}
            >
              <Card className="w-[15rem]">
                <Content
                  icon={(props) => (
                    <SvgXOctagon {...props} className="text-status-error-05" />
                  )}
                  title={
                    status === "connection_lost"
                      ? "Connection Lost Error"
                      : "Code Interpreter Error"
                  }
                  description={error}
                  variant="section"
                  sizePreset="main-ui"
                />
              </Card>
            </Section>
          )}
        </Section>
      </SettingsLayouts.Body>

      {showDisconnectModal && (
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title="Disconnect Code Interpreter"
          onClose={() => setShowDisconnectModal(false)}
          submit={
            <Button variant="danger" onClick={() => handleToggle(false)}>
              Disconnect
            </Button>
          }
        >
          <Text as="p" text03>
            All running sessions connected to{" "}
            <Text as="span" mainContentEmphasis text03>
              Code Interpreter
            </Text>{" "}
            will stop working. Note that this will not remove any data from your
            runtime. You can reconnect to this runtime later if needed.
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
