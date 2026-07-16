"use client";

import { useEffect, useRef, useState } from "react";
import { SettingsLayouts, toast } from "@opal/layouts";
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
import { Section } from "@/layouts/general-layouts";
import { Button, SelectCard } from "@opal/components";
import { Card, Content, ContentAction } from "@opal/layouts";
import { Disabled, Hoverable } from "@opal/core";
import Text from "@/refresh-components/texts/Text";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import useCodeInterpreter, {
  type CodeInterpreterHealthStatus,
} from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/views/admin/CodeInterpreterPage/svc";
import { cn } from "@opal/utils";

const route = ADMIN_ROUTES.CODE_INTERPRETER;

const STATUS_CONFIG: Record<
  CodeInterpreterHealthStatus,
  { label: string; icon: typeof SvgCheckCircle; iconColor: string }
> = {
  healthy: {
    label: "Connected",
    icon: SvgCheckCircle,
    iconColor: "text-status-success-05!",
  },
  unhealthy: {
    label: "Unhealthy",
    icon: SvgXOctagon,
    iconColor: "text-status-error-05!",
  },
  connection_lost: {
    label: "Connection Lost",
    icon: SvgXOctagon,
    iconColor: "text-status-error-05!",
  },
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

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
      <SvgSimpleLoader />
    </Section>
  );
}

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
  if (isLoading || !status) {
    return <CheckingStatus />;
  }

  const { label, icon: Icon, iconColor } = STATUS_CONFIG[status];
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
        className={cn(hasError && "cursor-pointer")}
      >
        <Icon size={16} className={iconColor} />
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CodeInterpreterPage() {
  const { status, error, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const isHealthy = status === "healthy";
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [showErrorMenu, setShowErrorMenu] = useState(false);
  const fadeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleErrorHover(hovered: boolean) {
    if (fadeTimeoutRef.current) {
      clearTimeout(fadeTimeoutRef.current);
      fadeTimeoutRef.current = null;
    }
    if (hovered) {
      setShowErrorMenu(true);
    } else {
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
                  title="Code Interpreter"
                  description="Built-in Python runtime"
                  padding="lg"
                  rightChildren={
                    <Section alignItems="end" gap={0}>
                      <ConnectionStatus
                        status={status}
                        isLoading={isLoading}
                        onIconHover={handleErrorHover}
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
                                tooltip="Disconnect"
                              />
                            </Hoverable.Item>
                          </Disabled>
                          <Button
                            disabled={isLoading}
                            prominence="tertiary"
                            size="md"
                            icon={SvgRefreshCw}
                            onClick={refetch}
                            tooltip="Refresh"
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
              title="Code Interpreter (Disconnected)"
              description="Built-in Python runtime"
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
                    Reconnect
                  </Button>
                )
              }
            />
          </SelectCard>
        )}
        {showErrorMenu && !isHealthy && (
          <Section
            flexDirection="row"
            justifyContent="end"
            onMouseEnter={() => handleErrorHover(true)}
            onMouseLeave={() => handleErrorHover(false)}
          >
            <div className="w-[15rem]">
              <SelectCard state="filled" padding="sm" rounding="lg">
                <Content
                  icon={(props) => (
                    <SvgXOctagon
                      {...props}
                      className={cn(props.className, "text-status-error-05!")}
                    />
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
              </SelectCard>
            </div>
          </Section>
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
