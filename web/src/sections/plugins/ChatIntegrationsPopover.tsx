"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSwitch,
  InputTypeIn,
  LineItemButton,
  Popover,
  Text,
} from "@opal/components";
import { SvgChevronRight, SvgPlug } from "@opal/icons";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { useFocusOnMount } from "@opal/hooks";
import { useNavigation } from "@opal/navigation";
import useScreenSize from "@/hooks/useScreenSize";
import { connectAction, needsAdmin } from "@/lib/integrations/connect";
import { useAppPosition } from "@/lib/navigation/hooks";
import {
  useAgentIntegrationPreferences,
  type AgentChatIntegrations,
} from "@/lib/integrations/hooks";
import type { MemberIntegration } from "@/lib/integrations/types";
import { useUser } from "@/providers/UserProvider";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { customizeTabHref } from "@/lib/customize/paths";
import { isIntegrationOnInChat } from "@/lib/integrations/chat";

export interface ChatIntegrationsPopoverProps {
  agentId: number;
  toolConfiguration: ToolConfigurationHandle;
  /** The integrations a chat of the agent uses for the user. */
  catalog: AgentChatIntegrations;
  disabled?: boolean;
  onConnect: (integration: MemberIntegration) => void;
  onBrowse: () => void;
}

/** One switch for each integration of the agent. The switch saves the
 * integrations that the user turned off for this agent. */
export default function ChatIntegrationsPopover({
  agentId,
  toolConfiguration,
  catalog,
  disabled = false,
  onConnect,
  onBrowse,
}: ChatIntegrationsPopoverProps) {
  const t = useTranslations("plugins.chat.popover");
  const stateCopy = useTranslations("integrations.memberState");
  const connectionCopy = useTranslations("plugins.member.connection");
  const { integrations, isLoading, refresh } = catalog;
  const { user } = useUser();
  const preferences = useAgentIntegrationPreferences(
    user !== null && !user.is_anonymous_user
  );
  const error = catalog.error ?? preferences.error;
  const appPosition = useAppPosition();
  const navigation = useNavigation();
  const { isMobile } = useScreenSize();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const trigger = useRef<HTMLElement | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const matching = integrations.filter((integration) =>
    integration.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())
  );
  const browseLink = navigation.linkTo(customizeTabHref("integrations"));

  function handleBrowse(event: React.MouseEvent<HTMLElement>) {
    if (appPosition.chat() === null) {
      toolConfiguration.handOffToNewChatWith(agentId, appPosition.project());
    }
    setOpen(false);
    onBrowse();
    browseLink.onClick(event);
  }

  function cancelHover() {
    if (hoverTimer.current !== null) clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
  }

  function changeOpen(next: boolean) {
    cancelHover();
    if (disabled && next) return;
    setOpen(next);
    if (next && !open) setSearch("");
  }

  function hover(next: boolean) {
    cancelHover();
    if (disabled && next) return;
    hoverTimer.current = setTimeout(() => changeOpen(next), next ? 100 : 250);
  }

  useEffect(
    () => () => {
      if (hoverTimer.current !== null) clearTimeout(hoverTimer.current);
    },
    []
  );

  function row(integration: MemberIntegration) {
    const required = integration.access.installation_policy === "REQUIRED";
    const enabled = isIntegrationOnInChat(
      integration,
      toolConfiguration.isIntegrationEnabled
    );
    const action = connectAction(integration);
    return (
      <LineItemButton
        font="main-ui-action"
        key={integration.id}
        title={integration.name}
        titleMaxLines={1}
        description={
          required
            ? stateCopy("switch.required")
            : needsAdmin(integration)
              ? connectionCopy("askAdmin")
              : undefined
        }
        descriptionMaxLines={1}
        icon={SvgPlug}
        padding={0}
        rounding={2}
        presentational
        rightChildren={
          <Section
            flexDirection="row"
            gap={0.5}
            width="auto"
            height="auto"
            alignItems="center"
          >
            {action && (
              <Button
                size="sm"
                prominence="secondary"
                disabled={disabled}
                onClick={() => {
                  setOpen(false);
                  // Connect shows that the member wants to use it.
                  if (!enabled && toolConfiguration.ready)
                    toolConfiguration.setIntegrationEnabled(
                      [integration.id],
                      true
                    );
                  onConnect(integration);
                }}
              >
                {connectionCopy(`${action}.label`)}
              </Button>
            )}
            <InputSwitch
              checked={enabled}
              disabled={disabled || required || !toolConfiguration.ready}
              aria-label={t("toggle.label", { name: integration.name })}
              onCheckedChange={(checked) =>
                toolConfiguration.setIntegrationEnabled(
                  [integration.id],
                  checked
                )
              }
            />
          </Section>
        }
      />
    );
  }

  return (
    <Popover open={open} onOpenChange={changeOpen}>
      <Popover.Trigger asChild>
        <LineItemButton
          font="main-ui-action"
          ref={trigger}
          disabled={disabled}
          icon={SvgPlug}
          title={t("trigger.label")}
          rounding={2}
          interaction={open ? "hover" : "rest"}
          aria-label={t("trigger.label")}
          rightChildren={
            <Section
              width={1.5}
              height={1.5}
              justifyContent="center"
              alignItems="center"
            >
              <SvgChevronRight size={16} />
            </Section>
          }
          onPointerEnter={(event) => {
            if (event.pointerType === "mouse") hover(true);
          }}
          onPointerLeave={(event) => {
            if (event.pointerType === "mouse") hover(false);
          }}
          onFocus={cancelHover}
          onClick={(event) => {
            event.preventDefault();
            changeOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key !== "ArrowRight") return;
            event.preventDefault();
            event.stopPropagation();
            changeOpen(true);
          }}
        />
      </Popover.Trigger>
      <Popover.Content
        // No room beside the parent menu on phones, so open over it.
        side={isMobile ? "top" : "right"}
        align={isMobile ? "start" : "end"}
        alignOffset={isMobile ? 0 : -5}
        width={60}
        aria-label={t("trigger.label")}
        onPointerEnter={cancelHover}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") hover(false);
        }}
        onCloseAutoFocus={(event) => event.preventDefault()}
        onEscapeKeyDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        }}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft") return;
          if (
            event.target instanceof HTMLInputElement &&
            event.target.selectionStart !== 0
          )
            return;
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        }}
      >
        <Popover.Menu
          gap={1}
          footer={
            <LineItemButton
              font="main-ui-action"
              title={t("browse.label")}
              icon={SvgPlug}
              href={browseLink.href}
              onClick={handleBrowse}
              padding={0}
              rounding={2}
            />
          }
        >
          {[
            <InputTypeIn
              key="search"
              ref={focusOnMount}
              icon="search"
              variant="internal"
              value={search}
              placeholder={t("search.placeholder")}
              aria-label={t("search.placeholder")}
              onChange={(event) => setSearch(event.target.value)}
            />,
            isLoading && (
              <Section
                key="loading"
                role="status"
                flexDirection="row"
                justifyContent="start"
                height="auto"
                gap={2}
                padding={2}
              >
                <IconLoader size={16} />
                <Text font="secondary-body" color="text-03">
                  {t("loading")}
                </Text>
              </Section>
            ),
            error && (
              <Section
                key="error"
                role="alert"
                alignItems="start"
                height="auto"
                gap={2}
                padding={2}
              >
                <Text font="secondary-body" color="status-error-05">
                  {t("loadError")}
                </Text>
                <Button
                  size="sm"
                  prominence="secondary"
                  onClick={() => {
                    void refresh();
                    void preferences.retry();
                  }}
                >
                  {t("retry.label")}
                </Button>
              </Section>
            ),
            ...matching.map(row),
            !isLoading && !error && matching.length === 0 && (
              <Section key="empty" alignItems="start" height="auto" padding={2}>
                <Text font="secondary-body" color="text-03">
                  {t(search ? "searchEmpty" : "empty")}
                </Text>
              </Section>
            ),
          ]}
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}
