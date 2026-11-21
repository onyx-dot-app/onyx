"use client";

import { IconLoader } from "@opal/loaders";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { SettingsLayouts, toast, Section } from "@opal/layouts";
import {
  SvgCheckCircle,
  SvgTerminal,
  SvgUnplug,
  SvgXOctagon,
} from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Popover, Text, useCreateModal } from "@opal/components";
import { Content, ReverseContent } from "@opal/layouts";
import { richNodes } from "@opal/utils";
import { IntegrationCard } from "@/sections/admin/IntegrationCard";
import { IntegrationConfirmModal } from "@/sections/admin/IntegrationConfirmModal";
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
    color: "success" | "error";
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
    color: "error",
  },
  connection_lost: {
    labelKey: "status.connectionLost.label",
    icon: SvgXOctagon,
    color: "error",
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
      <ReverseContent
        font="main-ui-body"
        icon={IconLoader}
        title={t("status.checking.label")}
        titleColor="text-03"
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
    <ReverseContent
      font="main-ui-body"
      icon={icon}
      title={t(labelKey)}
      color={color}
      titleColor="text-03"
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
  const disconnectModal = useCreateModal();
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

  // A card click and the refresh button both reconnect: they re-enable the
  // server and check it again.
  async function handleReconnect() {
    if (isReconnecting) return;
    setIsReconnecting(true);
    try {
      const response = await updateCodeInterpreter({ enabled: true });
      if (!response.ok) {
        toast.error(t("toggleError.reconnect.message"));
        return;
      }
      await refetch();
    } finally {
      setIsReconnecting(false);
    }
  }

  async function handleDisconnect() {
    const response = await updateCodeInterpreter({ enabled: false });
    if (!response.ok) throw new Error(t("toggleError.disconnect.message"));
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
            {/* The error popover opens under the whole card, not the status. */}
            <Popover.Anchor>
              <IntegrationCard
                icon={SvgTerminal}
                title={t("card.title")}
                description={t("card.description")}
                state="connected"
                broken={isConnectionLost}
                status={
                  <ConnectionStatus
                    status={status}
                    isLoading={isLoading}
                    onErrorHover={handleErrorHover}
                  />
                }
                busy={isLoading || isReconnecting}
                refreshing={isReconnecting}
                clickDisabled={isLoading}
                onRefresh={() => void handleReconnect()}
                onDisconnect={() => disconnectModal.toggle(true)}
                holdHover={disconnectModal.isOpen}
              />
            </Popover.Anchor>
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
                font="main-ui-action"
                icon={SvgXOctagon}
                color="error"
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
          <IntegrationCard
            icon={SvgTerminal}
            title={t("card.title")}
            description={t("card.description")}
            state="disconnected"
            busy={isReconnecting}
            status={<CheckingStatus />}
            onReconnect={() => void handleReconnect()}
            onDisconnect={() => disconnectModal.toggle(true)}
            onRefresh={() => void handleReconnect()}
          />
        )}
      </SettingsLayouts.Body>

      <disconnectModal.Provider>
        <IntegrationConfirmModal
          icon={SvgUnplug}
          title={t("disconnectModal.header.title")}
          submitLabel={t("disconnectModal.submitButton.label")}
          errorMessage={t("toggleError.disconnect.message")}
          onConfirm={handleDisconnect}
          onSettled={refetch}
        >
          <Text as="p" color="text-03">
            {richNodes(
              t.rich("disconnectModal.body.description", {
                emphasis: (chunks) => (
                  <Text as="span" font="main-content-emphasis" color="text-03">
                    {richNodes(chunks)}
                  </Text>
                ),
              })
            )}
          </Text>
        </IntegrationConfirmModal>
      </disconnectModal.Provider>
    </SettingsLayouts.Root>
  );
}
