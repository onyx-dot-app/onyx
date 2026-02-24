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
  rightContent: React.ReactNode;
}

function CodeInterpreterCard({
  variant,
  title,
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
          variant="tertiary"
        />
        {rightContent}
      </GeneralLayouts.Section>
    </Card>
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
      gap={0.2}
      padding={0}
    >
      <IconButton tertiary icon={SvgUnplug} tooltip="Disconnect" />
      <IconButton tertiary icon={SvgRefreshCw} tooltip="Test Connection" />
    </GeneralLayouts.Section>
  );
}

export default function CodeInterpreterPage() {
  const { isHealthy, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);

  async function handleDisconnect() {
    await updateCodeInterpreter({ enabled: false });
    setShowDisconnectModal(false);
    refetch();
  }

  async function handleReconnect() {
    await updateCodeInterpreter({ enabled: true });
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
            title="Code Interpreter (Disconnected)"
            rightContent={
              <Button
                tertiary
                rightIcon={SvgArrowExchange}
                onClick={handleReconnect}
              >
                <Text mainUiAction text03>
                  Reconnect
                </Text>
              </Button>
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
