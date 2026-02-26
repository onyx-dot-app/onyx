"use client";

import React, { useState } from "react";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Card, type CardProps } from "@/refresh-components/cards";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgRefreshCw,
  SvgTerminal,
  SvgUnplug,
  SvgXOctagon,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import useCodeInterpreter from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/lib/admin/code-interpreter/svc";
import { ContentAction } from "@opal/layouts";
import { toast } from "@/hooks/useToast";

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

interface ConnectionStatusProps {
  healthy: boolean;
  isLoading: boolean;
}

function ConnectionStatus({ healthy, isLoading }: ConnectionStatusProps) {
  if (isLoading) {
    return <CheckingStatus />;
  }

  const label = healthy ? "Connected" : "Connection Lost";
  const Icon = healthy ? SvgCheckCircle : SvgXOctagon;
  const iconColor = healthy ? "text-status-success-05" : "text-status-error-05";

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
      <Icon size={16} className={iconColor} />
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
      <Button
        prominence="tertiary"
        size="sm"
        icon={SvgUnplug}
        onClick={onDisconnect}
        tooltip="Disconnect"
        disabled={disabled}
      />
      <Button
        prominence="tertiary"
        size="sm"
        icon={SvgRefreshCw}
        onClick={onRefresh}
        tooltip="Refresh"
        disabled={disabled}
      />
    </Section>
  );
}

export default function CodeInterpreterPage() {
  const { isHealthy, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);

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

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgTerminal}
        title="Code Interpreter"
        description="Safe and sandboxed Python runtime available to your LLM. See docs for more details."
        separator
      />

      <SettingsLayouts.Body>
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
                <ConnectionStatus healthy={isHealthy} isLoading={isLoading} />
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
