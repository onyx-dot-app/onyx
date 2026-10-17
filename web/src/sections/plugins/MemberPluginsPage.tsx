"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, SelectCard, Text, Tooltip } from "@opal/components";
import { IllustrationContent, SettingsLayouts } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import {
  SvgChevronRight,
  SvgFileBraces,
  SvgPlus,
  SvgSettings,
} from "@opal/icons";
import { SvgUnPlugged } from "@opal/illustrations";
import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { getActionIcon } from "@/lib/tools/utils";
import {
  memberPluginName,
  memberPluginReference,
  useMemberPlugins,
  type MemberPlugin,
} from "@/lib/plugins/member";
import { memberPluginChatHref } from "@/lib/plugins/chat";
import type { PluginReference } from "@/lib/plugins/types";
import PluginRowLayout from "@/sections/plugins/PluginRowLayout";
import MemberPluginDetailModal from "@/sections/plugins/MemberPluginDetailModal";
import MemberPluginConnectionDialog from "@/sections/plugins/MemberPluginConnectionDialog";
import styles from "@/sections/plugins/PluginsPage.module.css";
import PluginDirectoryToolbar from "@/sections/plugins/PluginDirectoryToolbar";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import { CRAFT_PATH } from "@/app/craft/v1/constants";

type MemberPluginDialog =
  | { kind: "details"; reference: PluginReference }
  | { kind: "connect"; reference: PluginReference }
  | null;

function PluginConnectionStatus({
  plugin,
  onOpen,
}: {
  plugin: MemberPlugin;
  onOpen: () => void;
}) {
  const t = useTranslations("actions.memberPlugins");
  const connection = plugin.connection;
  const needsAuth =
    connection.kind === "oauth" || connection.kind === "credentials";
  const label = needsAuth
    ? t("filters.needsSignIn")
    : connection.kind === "connected"
      ? t(
          `status.${connection.ownership === "user" ? "connected" : connection.ownership}`
        )
      : t(`status.${connection.kind}`);

  function StatusIcon({ className }: IconProps) {
    return (
      <span
        aria-hidden
        className={cn(
          "block size-3 rounded-full",
          needsAuth
            ? "bg-status-warning-05"
            : connection.kind === "connected"
              ? "bg-status-success-05"
              : "bg-text-03",
          className
        )}
      />
    );
  }

  return (
    <Tooltip
      tone="neutral"
      side="top"
      sideOffset={6}
      delayDuration={250}
      tooltip={<Text font="secondary-body">{label}</Text>}
    >
      <Button
        icon={StatusIcon}
        size="sm"
        prominence="tertiary"
        aria-label={t("availability.label", { name: memberPluginName(plugin) })}
        onClick={(event) => {
          event.stopPropagation();
          onOpen();
        }}
      />
    </Tooltip>
  );
}

function MemberPluginRow({
  plugin,
  onDetails,
  onConnect,
}: {
  plugin: MemberPlugin;
  onDetails: () => void;
  onConnect: () => void;
}) {
  const t = useTranslations("actions.memberPlugins");
  const name = memberPluginName(plugin);
  const connection = plugin.connection;
  const connectable =
    connection.kind === "oauth" || connection.kind === "credentials";
  const status =
    connection.kind === "connected" || connectable
      ? null
      : t(`status.${connection.kind}`);

  return (
    <SelectCard
      border="none"
      padding={0}
      aria-label={t("row.view", { name })}
      onClick={onDetails}
    >
      <PluginRowLayout
        icon={
          plugin.kind === "external-app"
            ? getAppTypeLogo(plugin.app.app_type)
            : plugin.kind === "mcp"
              ? getActionIcon(plugin.server.server_url, name)
              : SvgFileBraces
        }
        title={name}
        description={
          plugin.kind === "external-app"
            ? t("externalApp.description")
            : plugin.kind === "mcp"
              ? plugin.server.description || plugin.server.server_url
              : plugin.tool.description
        }
        status={
          status ? (
            <Text font="secondary-body" color="text-03">
              {status}
            </Text>
          ) : undefined
        }
        descriptionTag={
          plugin.kind === "external-app"
            ? {
                title: t("externalApp.craftOnly"),
                color: "gray",
                tooltip: t("externalApp.craftOnlyDescription"),
              }
            : plugin.kind === "openapi"
              ? {
                  title: t("openapi.chatOnly"),
                  color: "gray",
                  tooltip: t("openapi.chatOnlyDescription"),
                }
              : undefined
        }
        action={
          <>
            <Text font="secondary-body" color="text-03">
              {t(`kind.${plugin.kind}`)}
            </Text>
            <PluginConnectionStatus plugin={plugin} onOpen={onDetails} />
            <Button
              icon={connectable ? SvgPlus : SvgChevronRight}
              size="sm"
              prominence="tertiary"
              aria-label={t(connectable ? "row.connect" : "row.view", { name })}
              onClick={(event) => {
                event.stopPropagation();
                if (connectable) onConnect();
                else onDetails();
              }}
            />
          </>
        }
      />
    </SelectCard>
  );
}

interface MemberPluginsPageProps {
  initialFilter?: "all" | "connected" | "needsSignIn";
  surface?: "all" | "craft";
}

export default function MemberPluginsPage({
  initialFilter = "all",
  surface = "all",
}: MemberPluginsPageProps) {
  const t = useTranslations("actions.memberPlugins");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { plugins, isLoading, loading, errors, refresh } = useMemberPlugins({
    surface,
  });
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const [filter, setFilter] = useState(initialFilter);
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<MemberPluginDialog>(null);
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = plugins.filter((plugin) => {
    if (
      surface === "craft" &&
      (plugin.kind === "openapi" ||
        (plugin.kind === "mcp" && plugin.server.available_in_craft !== true))
    )
      return false;
    if (filter === "connected" && plugin.connection.kind !== "connected")
      return false;
    if (
      filter === "needsSignIn" &&
      plugin.connection.kind !== "oauth" &&
      plugin.connection.kind !== "credentials"
    )
      return false;
    const description =
      plugin.kind === "external-app"
        ? plugin.app.app_type
        : plugin.kind === "mcp"
          ? `${plugin.server.description ?? ""} ${plugin.server.server_url}`
          : plugin.tool.description;
    return `${memberPluginName(plugin)} ${description}`
      .toLowerCase()
      .includes(normalizedQuery);
  });
  const activePlugin =
    dialog &&
    plugins.find((plugin) => {
      const reference = memberPluginReference(plugin);
      return (
        reference.kind === dialog.reference.kind &&
        reference.id === dialog.reference.id
      );
    });
  const hasErrors = Boolean(
    errors.apps || errors.servers || errors.tools || errors.oauth
  );
  const handledConnect = useRef<string | null>(null);
  const connectIntent = searchParams.get("connect");

  useEffect(() => {
    if (!connectIntent) {
      handledConnect.current = null;
      return;
    }
    if (
      handledConnect.current === connectIntent ||
      !/^[1-9]\d*$/.test(connectIntent)
    )
      return;
    const plugin = plugins.find(
      (item) =>
        item.kind === "external-app" && item.app.id === Number(connectIntent)
    );
    if (!plugin) return;
    handledConnect.current = connectIntent;
    setDialog({
      kind:
        plugin.connection.kind === "oauth" ||
        plugin.connection.kind === "credentials"
          ? "connect"
          : "details",
      reference: memberPluginReference(plugin),
    });
  }, [connectIntent, plugins]);

  function show(plugin: MemberPlugin, kind: "details" | "connect") {
    setDialog({ kind, reference: memberPluginReference(plugin) });
  }

  return (
    <div className={styles.directory}>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          title={t("title")}
          description={t("description")}
          stackActionsOnMobile
          actions={
            isGlobalHolder || isScopedManager
              ? [
                  <Button
                    key="manage"
                    href="/admin/plugins"
                    icon={SvgSettings}
                    prominence="secondary"
                  >
                    {t("manageWorkspace")}
                  </Button>,
                ]
              : []
          }
        />
        <SettingsLayouts.Body>
          <div className="flex flex-col gap-4">
            <PluginDirectoryToolbar
              searchLabel={t("search")}
              query={query}
              onQueryChange={setQuery}
              filters={
                <div
                  role="group"
                  aria-label={t("filters.label")}
                  className="flex flex-wrap gap-2"
                >
                  {(["all", "connected", "needsSignIn"] as const).map(
                    (value) => (
                      <Button
                        key={value}
                        size="sm"
                        prominence={filter === value ? "primary" : "tertiary"}
                        aria-pressed={filter === value}
                        onClick={() => setFilter(value)}
                      >
                        {t(`filters.${value}`)}
                      </Button>
                    )
                  )}
                </div>
              }
            />
            <div className={styles.results}>
              {(["apps", "servers", "tools", "oauth"] as const).map(
                (source) =>
                  errors[source] && (
                    <div
                      key={source}
                      role="alert"
                      className="flex items-center justify-between gap-4 rounded-12 border border-border-01 px-4 py-3"
                    >
                      <Text font="secondary-body" color="text-03">
                        {t(`state.${source}Error`)}
                      </Text>
                      <Button
                        size="sm"
                        prominence="secondary"
                        onClick={() => void refresh()}
                      >
                        {t("state.retry")}
                      </Button>
                    </div>
                  )
              )}
              {loading.apps && (
                <div role="status" aria-label={t("state.appsLoading")}>
                  <Text font="secondary-body" color="text-03">
                    {t("state.appsLoading")}
                  </Text>
                </div>
              )}
              {isLoading && (
                <div
                  role="status"
                  aria-label={t("state.loading")}
                  className={styles.grid}
                >
                  {[0, 1].map((index) => (
                    <div
                      key={index}
                      className="flex items-center gap-4 px-3 py-4"
                    >
                      <div className="opal-shimmer-block size-[42px] shrink-0 rounded-12" />
                      <LineLoader lines={2} width="2/3" />
                    </div>
                  ))}
                </div>
              )}
              {filtered.length > 0 && (
                <div className={styles.grid}>
                  {filtered.map((plugin) => {
                    const reference = memberPluginReference(plugin);
                    return (
                      <MemberPluginRow
                        key={`${reference.kind}-${reference.id}`}
                        plugin={plugin}
                        onDetails={() => show(plugin, "details")}
                        onConnect={() => show(plugin, "connect")}
                      />
                    );
                  })}
                </div>
              )}
              {!filtered.length && !isLoading && !hasErrors && (
                <div className="flex min-h-72 flex-col items-center justify-center gap-3 py-12">
                  <div className="max-w-sm">
                    <IllustrationContent
                      illustration={SvgUnPlugged}
                      title={t(
                        normalizedQuery
                          ? "state.noResultsTitle"
                          : "state.emptyTitle"
                      )}
                      description={t(
                        normalizedQuery
                          ? "state.noResultsDescription"
                          : "state.emptyDescription"
                      )}
                    />
                  </div>
                  <div className="flex min-h-8 items-center justify-center">
                    {normalizedQuery ? (
                      <Button
                        prominence="secondary"
                        onClick={() => {
                          setQuery("");
                          setFilter("all");
                        }}
                      >
                        {t("state.clearSearch")}
                      </Button>
                    ) : filter !== "all" ? (
                      <Button
                        prominence="secondary"
                        onClick={() => setFilter("all")}
                      >
                        {t("filters.showAll")}
                      </Button>
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
      {activePlugin && dialog?.kind === "details" && (
        <MemberPluginDetailModal
          key={`${dialog.reference.kind}-${dialog.reference.id}`}
          plugin={activePlugin}
          surface={surface}
          open
          onClose={() => setDialog(null)}
          onConnect={() => show(activePlugin, "connect")}
          onOpenInCraft={() => router.push(CRAFT_PATH)}
          onUseInChat={() => {
            const reference = memberPluginReference(activePlugin);
            if (reference.kind === "external-app") return;
            router.push(
              memberPluginChatHref(reference, searchParams.get("returnTo"))
            );
          }}
          onDisconnected={() => {
            setDialog(null);
            void refresh();
          }}
        />
      )}
      {activePlugin && dialog?.kind === "connect" && (
        <MemberPluginConnectionDialog
          plugin={activePlugin}
          open
          onClose={() => setDialog(null)}
          onConnected={() => {
            show(activePlugin, "details");
            void refresh();
          }}
        />
      )}
    </div>
  );
}
