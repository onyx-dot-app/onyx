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
import { SvgBlocks, SvgChevronRight, SvgPlug } from "@opal/icons";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { useFocusOnMount } from "@opal/hooks";
import { useNavigation } from "@opal/navigation";
import useScreenSize from "@/hooks/useScreenSize";
import { connectAction, needsAdmin } from "@/lib/integrations/connect";
import { useAppPosition } from "@/lib/navigation/hooks";
import {
  useAgentPluginPreferences,
  type AgentChatPlugins,
  type ChatPluginEntry,
} from "@/lib/plugins/hooks";
import { useUser } from "@/providers/UserProvider";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";

export interface ChatPluginsPopoverProps {
  agentId: number;
  toolConfiguration: ToolConfigurationHandle;
  /** The agent's plugins (persona detail `plugins`). */
  catalog: AgentChatPlugins;
  disabled?: boolean;
  onConnect: (plugin: ChatPluginEntry) => void;
  onBrowse: () => void;
}

export default function ChatPluginsPopover({
  agentId,
  toolConfiguration,
  catalog,
  disabled = false,
  onConnect,
  onBrowse,
}: ChatPluginsPopoverProps) {
  const t = useTranslations("plugins.chat.popover");
  const memberCopy = useTranslations("plugins.member");
  const connectionCopy = useTranslations("plugins.member.connection");
  const { plugins, isLoading, refresh } = catalog;
  const { user } = useUser();
  const preferences = useAgentPluginPreferences(
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
  const matching = plugins.filter((plugin) =>
    plugin.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())
  );
  const browseLink = navigation.linkTo("/app/plugins");

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

  function row(plugin: ChatPluginEntry) {
    const adminOnly = plugin.integrations.every(needsAdmin);
    const enabled =
      plugin.required || toolConfiguration.isPluginEnabled(plugin.pluginId);
    const action =
      plugin.integrations.map(connectAction).find((a) => a !== null) ?? null;
    return (
      <LineItemButton
        font="main-ui-action"
        key={plugin.pluginId}
        title={plugin.name}
        titleMaxLines={1}
        description={
          plugin.required
            ? memberCopy("detail.switch.required")
            : adminOnly
              ? connectionCopy("askAdmin")
              : undefined
        }
        descriptionMaxLines={1}
        icon={SvgBlocks}
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
                  // Connect shows that the member wants to use the plugin.
                  if (!enabled && toolConfiguration.ready)
                    toolConfiguration.setPluginEnabled([plugin.pluginId], true);
                  onConnect(plugin);
                }}
              >
                {connectionCopy(`${action}.label`)}
              </Button>
            )}
            <InputSwitch
              checked={enabled}
              disabled={disabled || plugin.required || !toolConfiguration.ready}
              aria-label={t("toggle.label", { name: plugin.name })}
              onCheckedChange={(checked) =>
                toolConfiguration.setPluginEnabled([plugin.pluginId], checked)
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
              placeholder={memberCopy("search.placeholder")}
              aria-label={memberCopy("search.placeholder")}
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
