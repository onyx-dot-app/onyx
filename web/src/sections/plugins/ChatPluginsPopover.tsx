"use client";

import { useMemo, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSwitch,
  InputTypeIn,
  LineItemButton,
  Popover,
  Text,
} from "@opal/components";
import { SvgFileBraces, SvgPlug } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { useFocusOnMount } from "@opal/hooks";
import type { MinimalAgent } from "@/lib/agents/types";
import {
  chatPluginsForAgent,
  isChatPluginEnabled,
  memberPluginsHref,
  setChatPluginEnabled,
} from "@/lib/plugins/chat";
import {
  memberPluginName,
  memberPluginReference,
  useMemberPlugins,
  type MemberPlugin,
} from "@/lib/plugins/member";
import { useAppPosition } from "@/lib/position/hooks";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { getActionIcon } from "@/lib/tools/utils";
import MemberPluginConnectionDialog from "@/sections/plugins/MemberPluginConnectionDialog";

export interface ChatPluginsPopoverProps {
  agent: MinimalAgent;
  toolConfiguration: ToolConfigurationHandle;
  disabled?: boolean;
}

export default function ChatPluginsPopover({
  agent,
  toolConfiguration,
  disabled = false,
}: ChatPluginsPopoverProps) {
  const t = useTranslations("actions.memberPlugins");
  const { plugins, isLoading, errors, refresh } = useMemberPlugins({
    surface: "chat",
    agentId: agent.id,
  });
  const appPosition = useAppPosition();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [connecting, setConnecting] = useState<MemberPlugin | null>(null);
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const attached = useMemo(
    () => chatPluginsForAgent(plugins, agent),
    [plugins, agent]
  );
  const matching = attached.filter(({ plugin }) =>
    memberPluginName(plugin)
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase())
  );
  const hasError = Boolean(errors.servers || errors.tools || errors.oauth);
  const returnTo =
    pathname === "/app"
      ? `/app?${searchParams?.toString() ?? ""}`
      : `/app?agentId=${agent.id}`;

  function handleBrowse() {
    if (appPosition.chat() === null) {
      toolConfiguration.handOffToNewChatWith(agent.id, appPosition.project());
    }
    setOpen(false);
  }

  function connect(plugin: MemberPlugin) {
    setOpen(false);
    setConnecting(plugin);
  }

  return (
    <>
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) setSearch("");
        }}
      >
        <Popover.Trigger asChild>
          <Button
            disabled={disabled}
            icon={SvgPlug}
            prominence="tertiary"
            interaction={open ? "hover" : "rest"}
            tooltip={t("chat.trigger.label")}
            aria-label={t("chat.trigger.label")}
          />
        </Popover.Trigger>
        <Popover.Content side="bottom" align="start" width="lg">
          <Popover.Menu
            gap={1}
            footer={
              <LineItemButton
                title={t("chat.browse.label")}
                icon={SvgPlug}
                href={memberPluginsHref(returnTo)}
                onClick={handleBrowse}
                sizePreset="main-ui"
                padding={0}
                rounding={2}
              />
            }
          >
            {[
              <InputTypeIn
                key="search"
                ref={focusOnMount}
                searchIcon
                variant="internal"
                value={search}
                placeholder={t("chat.search.placeholder")}
                aria-label={t("chat.search.placeholder")}
                onChange={(event) => setSearch(event.target.value)}
              />,
              isLoading && (
                <div
                  key="loading"
                  role="status"
                  className="flex items-center gap-2 p-2"
                >
                  <IconLoader size={16} />
                  <Text font="secondary-body" color="text-03">
                    {t("chat.loading.label")}
                  </Text>
                </div>
              ),
              hasError && (
                <div
                  key="error"
                  role="alert"
                  className="flex flex-col gap-2 p-2"
                >
                  <Text font="secondary-body" color="status-error-05">
                    {t("chat.loadError.text")}
                  </Text>
                  <Button
                    size="sm"
                    prominence="secondary"
                    onClick={() => void refresh()}
                  >
                    {t("chat.retry.label")}
                  </Button>
                </div>
              ),
              ...matching.map((group) => {
                const { plugin } = group;
                const reference = memberPluginReference(plugin);
                const name = memberPluginName(plugin);
                const needsConnection =
                  plugin.connection.kind === "oauth" ||
                  plugin.connection.kind === "credentials";
                const unavailable =
                  plugin.connection.kind === "checking" ||
                  plugin.connection.kind === "unconfigured" ||
                  plugin.connection.kind === "unavailable";
                const enabled = isChatPluginEnabled(group, toolConfiguration);
                return (
                  <LineItemButton
                    key={`${reference.kind}:${reference.id}`}
                    title={name}
                    titleMaxLines={1}
                    description={
                      plugin.connection.kind === "connected" || needsConnection
                        ? undefined
                        : t(`chat.connection.${plugin.connection.kind}`)
                    }
                    descriptionMaxLines={1}
                    icon={
                      plugin.kind === "mcp"
                        ? getActionIcon(
                            plugin.server.server_url,
                            plugin.server.name
                          )
                        : SvgFileBraces
                    }
                    sizePreset="main-ui"
                    padding={0}
                    rounding={2}
                    presentational
                    rightChildren={
                      needsConnection ? (
                        <Button
                          size="sm"
                          prominence="secondary"
                          disabled={disabled}
                          onClick={() => connect(plugin)}
                        >
                          {t("chat.connect.label")}
                        </Button>
                      ) : (
                        <InputSwitch
                          checked={enabled}
                          disabled={
                            disabled ||
                            !toolConfiguration.ready ||
                            (unavailable && !enabled)
                          }
                          aria-label={t("chat.toggle.ariaLabel", { name })}
                          onCheckedChange={(enabled) =>
                            setChatPluginEnabled(
                              group,
                              enabled,
                              toolConfiguration
                            )
                          }
                        />
                      )
                    }
                  />
                );
              }),
              !isLoading && !hasError && matching.length === 0 && (
                <div key="empty" className="p-2">
                  <Text font="secondary-body" color="text-03">
                    {t(search ? "chat.empty.searchText" : "chat.empty.text")}
                  </Text>
                </div>
              ),
            ]}
          </Popover.Menu>
        </Popover.Content>
      </Popover>
      {connecting && (
        <MemberPluginConnectionDialog
          plugin={connecting}
          open
          onClose={() => setConnecting(null)}
          onConnected={() => {
            const reference = memberPluginReference(connecting);
            const group = attached.find(({ plugin }) => {
              const candidate = memberPluginReference(plugin);
              return (
                candidate.kind === reference.kind &&
                candidate.id === reference.id
              );
            });
            if (group) setChatPluginEnabled(group, true, toolConfiguration);
            setConnecting(null);
            void refresh();
          }}
        />
      )}
    </>
  );
}
