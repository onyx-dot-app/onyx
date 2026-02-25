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
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import useCodeInterpreter from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/lib/admin/code-interpreter/svc";

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
    <Card variant={variant}>
      <GeneralLayouts.Section
        flexDirection="row"
        alignItems="start"
        padding={0}
        gap={0}
      >
        <GeneralLayouts.LineItemLayout
          icon={SvgTerminal}
          title={title}
          description="Built-in Python runtime"
          middleText={middleText}
          variant="tertiary"
          strikethrough={strikethrough}
        />
        {rightContent}
      </GeneralLayouts.Section>
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
      <IconButton tertiary icon={SvgUnplug} onClick={onDisconnect} />
      <IconButton tertiary icon={SvgRefreshCw} onClick={onRefresh} />
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
                  tertiary
                  rightIcon={SvgArrowExchange}
                  onClick={handleReconnect}
                >
                  <Text mainUiAction text03>
                    Reconnect
                  </Text>
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
            <Button danger onClick={handleDisconnect}>
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
