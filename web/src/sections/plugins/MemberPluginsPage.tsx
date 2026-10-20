"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Button, Modal, SelectCard, Text, Tooltip } from "@opal/components";
import { IllustrationContent, SettingsLayouts } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import {
  SvgChevronRight,
  SvgCodeFile,
  SvgPlus,
  SvgSettings,
} from "@opal/icons";
import { SvgUnPlugged } from "@opal/illustrations";
import type { IconProps } from "@opal/types";
import PluginStatusIcon from "@/sections/plugins/PluginStatusIcon";
import { useSettings } from "@/lib/settings/hooks";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { getActionIcon } from "@/lib/tools/utils";
import {
  memberPluginName,
  memberPluginReference,
  useMemberPlugins,
  type MemberPlugin,
} from "@/lib/plugins/member";
import type { PluginReference } from "@/lib/plugins/types";
import PluginRowLayout from "@/sections/plugins/PluginRowLayout";
import { MemberPluginDetailContent } from "@/sections/plugins/MemberPluginDetailModal";
import { MemberPluginConnectionContent } from "@/sections/plugins/MemberPluginConnectionDialog";
import styles from "@/sections/plugins/PluginsPage.module.css";
import PluginDirectoryToolbar from "@/sections/plugins/PluginDirectoryToolbar";
import { useExternalAppsWithSkillIssues } from "@/lib/externalApps/hooks";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";

import {
  memberPluginStatus,
  memberPluginSurfaceStatus,
  memberPluginSurfaceAvailability,
  MEMBER_PLUGIN_SURFACES,
  sortPlugins,
} from "@/lib/plugins/sort";

type MemberPluginDialog =
  | { kind: "details"; reference: PluginReference; initialTab?: "approvals" }
  | { kind: "connect"; reference: PluginReference }
  | null;

function PluginConnectionStatus({
  plugin,
  onOpen,
  hasSkillIssues = false,
  craftAvailable,
}: {
  plugin: MemberPlugin;
  onOpen: () => void;
  hasSkillIssues?: boolean;
  craftAvailable: boolean;
}) {
  const t = useTranslations("actions.memberPlugins");
  const skillCopy = useTranslations("craft.apps.page.status");
  const connection = plugin.connection;
  const needsAuth =
    connection.kind === "oauth" || connection.kind === "credentials";
  const skillWarning = connection.kind === "connected" && hasSkillIssues;
  const availabilityCopy = useTranslations("actions.plugins.availability");
  const connectionLabel = needsAuth
    ? t("filters.needsSignIn")
    : connection.kind === "connected"
      ? t("status.none")
      : t(`status.${connection.kind}`);

  const requiresWorkspaceSetup = connection.kind === "unconfigured";

  function StatusIcon(props: IconProps) {
    if (requiresWorkspaceSetup)
      return <PluginStatusIcon {...props} primary="inactive" />;
    return (
      <PluginStatusIcon
        {...props}
        primary={memberPluginSurfaceStatus(
          plugin,
          "chat",
          hasSkillIssues,
          craftAvailable
        )}
        secondary={memberPluginSurfaceStatus(
          plugin,
          "agents",
          hasSkillIssues,
          craftAvailable
        )}
        tertiary={memberPluginSurfaceStatus(
          plugin,
          "craft",
          hasSkillIssues,
          craftAvailable
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
      tooltip={
        requiresWorkspaceSetup ? (
          <Text font="secondary-body">{connectionLabel}</Text>
        ) : (
          <div className="grid grid-cols-[auto_auto] gap-x-6 gap-y-1.5">
            {MEMBER_PLUGIN_SURFACES.map((item) => {
              const { supported, available, personallyEnabled } =
                memberPluginSurfaceAvailability(plugin, item, craftAvailable);
              const value = !supported
                ? t("availability.notAvailable")
                : connection.kind !== "connected"
                  ? connectionLabel
                  : item === "craft" && skillWarning
                    ? skillCopy("skillWarningSummary")
                    : available === false
                      ? t("availability.disabledByAdmin")
                      : personallyEnabled === false
                        ? t("availability.disabledByYou")
                        : available === true
                          ? t("status.none")
                          : availabilityCopy("unknown");
              return (
                <div key={item} className="contents">
                  <Text font="secondary-body" color="text-03">
                    {item === "agents"
                      ? t("availability.agents")
                      : availabilityCopy(
                          item === "chat" ? "mainChat" : "craft"
                        )}
                  </Text>
                  <Text font="secondary-body">{value}</Text>
                </div>
              );
            })}
          </div>
        )
      }
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
  craftAvailable,
  hasSkillIssues,
  onDetails,
  onConnect,
}: {
  plugin: MemberPlugin;
  hasSkillIssues: boolean;
  craftAvailable: boolean;
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
              : SvgCodeFile
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
        action={
          <>
            <Text font="secondary-body" color="text-03">
              {t(`kind.${plugin.kind}`)}
            </Text>
            <PluginConnectionStatus
              plugin={plugin}
              onOpen={onDetails}
              hasSkillIssues={hasSkillIssues}
              craftAvailable={craftAvailable}
            />
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
  const locale = useLocale();
  const craftAvailable = useSettings().onyx_craft_enabled === true;
  const [filter, setFilter] = useState(initialFilter);
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<MemberPluginDialog>(null);
  const appsWithSkillIssues = useExternalAppsWithSkillIssues(
    plugins.some(
      (plugin) =>
        plugin.kind === "external-app" && plugin.connection.kind === "connected"
    )
  );
  const hasSkillIssues = (plugin: MemberPlugin) =>
    plugin.kind === "external-app" && appsWithSkillIssues.has(plugin.app.id);
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = sortPlugins(
    plugins,
    (plugin) =>
      memberPluginStatus(plugin, hasSkillIssues(plugin), craftAvailable),
    memberPluginName,
    locale
  ).filter((plugin) => {
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
  const policyIntent = searchParams.get("actionPolicies");
  const handledPolicy = useRef<string | null>(null);

  useEffect(() => {
    if (!policyIntent) {
      handledPolicy.current = null;
      return;
    }
    if (handledPolicy.current === policyIntent) return;
    const match = /^(app|mcp)-(\d+)$/.exec(policyIntent);
    if (!match) return;
    const plugin = plugins.find((item) =>
      match[1] === "app"
        ? item.kind === "external-app" && item.app.id === Number(match[2])
        : item.kind === "mcp" && item.server.id === Number(match[2])
    );
    if (!plugin) return;
    handledPolicy.current = policyIntent;
    const needsConnection =
      plugin.connection.kind === "oauth" ||
      plugin.connection.kind === "credentials";
    setDialog(
      needsConnection
        ? { kind: "connect", reference: memberPluginReference(plugin) }
        : {
            kind: "details",
            reference: memberPluginReference(plugin),
            initialTab: "approvals",
          }
    );
  }, [policyIntent, plugins]);

  function closeDialog() {
    setDialog(null);
    if (!policyIntent) return;
    handledConnect.current = connectIntent;
    const params = new URLSearchParams(searchParams.toString());
    params.delete("actionPolicies");
    const query = params.toString();
    const path = surface === "craft" ? "/craft/v1/plugins" : "/app/plugins";
    router.replace(query ? `${path}?${query}` : path, { scroll: false });
  }

  useEffect(() => {
    if (policyIntent) return;
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
  }, [connectIntent, plugins, policyIntent]);

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
                        hasSkillIssues={hasSkillIssues(plugin)}
                        craftAvailable={craftAvailable}
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
      <Modal open={Boolean(activePlugin && dialog)}>
        <Modal.Backdrop />
        {activePlugin && dialog?.kind === "details" && (
          <MemberPluginDetailContent
            key={`${dialog.reference.kind}-${dialog.reference.id}`}
            plugin={activePlugin}
            surface={surface}
            initialTab={dialog.initialTab}
            open
            skipOverlay
            onClose={closeDialog}
            onConnect={() => show(activePlugin, "connect")}
            onDisconnected={() => {
              closeDialog();
              void refresh();
            }}
          />
        )}
        {activePlugin && dialog?.kind === "connect" && (
          <MemberPluginConnectionContent
            key={`${dialog.reference.kind}-${dialog.reference.id}`}
            plugin={activePlugin}
            surface={surface}
            skipOverlay
            onClose={closeDialog}
            onConnected={() => {
              show(activePlugin, "details");
              void refresh();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
