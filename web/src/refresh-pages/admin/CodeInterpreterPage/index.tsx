"use client";

import { useState } from "react";
import { SettingsLayouts } from "@opal/layouts";
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
import useCodeInterpreter from "@/hooks/useCodeInterpreter";
import { updateCodeInterpreter } from "@/refresh-pages/admin/CodeInterpreterPage/svc";
import { toast } from "@/hooks/useToast";
import { cn } from "@opal/utils";

const route = ADMIN_ROUTES.CODE_INTERPRETER;

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
        正在检查...
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
  if (isLoading) {
    return <CheckingStatus />;
  }

  const label = healthy ? "已连接" : "连接丢失";
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
  const { isHealthy, isEnabled, isLoading, refetch } = useCodeInterpreter();
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);

  async function handleToggle(enabled: boolean) {
    setIsReconnecting(enabled);
    try {
      const response = await updateCodeInterpreter({ enabled });
      if (!response.ok) {
        toast.error(`${enabled ? "重新连接" : "断开"}代码解释器失败`);
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
        title={route.title}
        description="为 LLM 提供安全、沙盒化的 Python 运行时。更多详情请查看文档。"
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
                  title="代码解释器"
                  description="内置 Python 运行时"
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
                                tooltip="断开连接"
                              />
                            </Hoverable.Item>
                          </Disabled>
                          <Button
                            disabled={isLoading}
                            prominence="tertiary"
                            size="md"
                            icon={SvgRefreshCw}
                            onClick={refetch}
                            tooltip="刷新"
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
              title="代码解释器（已断开）"
              description="内置 Python 运行时"
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
                    重新连接
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
          title="断开代码解释器"
          onClose={() => setShowDisconnectModal(false)}
          submit={
            <Button variant="danger" onClick={() => handleToggle(false)}>
              断开连接
            </Button>
          }
        >
          <Text as="p" text03>
            所有连接到{" "}
            <Text as="span" mainContentEmphasis text03>
              代码解释器
            </Text>{" "}
            的运行中会话都将停止工作。此操作不会删除运行时中的任何数据。
            需要时你可以稍后重新连接此运行时。
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
