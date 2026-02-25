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
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import useCodeInterpreter from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/lib/admin/code-interpreter/svc";
import { ContentAction } from "@opal/layouts";

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
    <Card variant={variant}>
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

interface ConnectionStatusProps {
  healthy: boolean;
  isLoading: boolean;
}

function ConnectionStatus({ healthy, isLoading }: ConnectionStatusProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      gap={0.4}
      padding={0}
      justifyContent="end"
      alignItems="center"
    >
      {isLoading ? (
        <>
          <Text mainUiAction text03>
            Checking...
          </Text>
          <SimpleLoader />
        </>
      ) : (
        <>
          <Text mainUiAction text03>
            {healthy ? "Connected" : "Connection Lost"}
          </Text>
          {healthy ? (
            <SvgCheckCircle size={16} className="text-status-success-05" />
          ) : (
            <SvgXOctagon size={16} className="text-status-error-05" />
          )}
        </>
      )}
    </GeneralLayouts.Section>
  );
}

interface ActionButtonsProps {
  onDisconnect: () => void;
  onRefresh: () => void;
}

function ActionButtons({ onDisconnect, onRefresh }: ActionButtonsProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="end"
      gap={0}
      padding={0}
    >
      <Button
        prominence="tertiary"
        size="sm"
        icon={SvgUnplug}
        onClick={onDisconnect}
        tooltip="Disconnect"
      />
      <Button
        prominence="tertiary"
        size="sm"
        icon={SvgRefreshCw}
        onClick={onRefresh}
        tooltip="Refresh"
      />
    </GeneralLayouts.Section>
  );
}

export default function CodeInterpreterPage() {
  const { isHealthy, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);

  async function handleDisconnect() {
    const response = await updateCodeInterpreter({ enabled: false });
    if (!response.ok) {
      return;
    }
    setShowDisconnectModal(false);
    refetch();
  }

  async function handleReconnect() {
    setIsReconnecting(true);
    const response = await updateCodeInterpreter({ enabled: true });
    setIsReconnecting(false);
    if (!response.ok) {
      return;
    }
    refetch();
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
        {isEnabled ? (
          <CodeInterpreterCard
            title="Code Interpreter"
            variant={isHealthy ? "primary" : "secondary"}
            strikethrough={!isHealthy}
            rightContent={
              <GeneralLayouts.Section flexDirection="column" gap={0.5}>
                <ConnectionStatus healthy={isHealthy} isLoading={isLoading} />
                <ActionButtons
                  onDisconnect={() => setShowDisconnectModal(true)}
                  onRefresh={refetch}
                />
              </GeneralLayouts.Section>
            }
          />
        ) : (
          <CodeInterpreterCard
            variant="secondary"
            title="Code Interpreter"
            middleText="(Disconnected)"
            strikethrough={true}
            rightContent={
              isReconnecting ? (
                <GeneralLayouts.Section
                  flexDirection="row"
                  gap={0.4}
                  padding={0}
                  justifyContent="end"
                  alignItems="center"
                >
                  <Text mainUiAction text03>
                    Checking...
                  </Text>
                  <SimpleLoader />
                </GeneralLayouts.Section>
              ) : (
                <Button
                  prominence="tertiary"
                  rightIcon={SvgArrowExchange}
                  onClick={handleReconnect}
                >
                  Reconnect
                </Button>
              )
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
            <Button variant="danger" onClick={handleDisconnect}>
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
