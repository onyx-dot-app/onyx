"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, Dropdown, Tabs, Text } from "@opal/components";
import { SearchNoResults } from "@/lib/common/components";
import type { RichStr } from "@opal/types";
import { markdown } from "@opal/utils";
import {
  ContentAction,
  IllustrationContent,
  SettingsLayouts,
} from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import { SvgEmpty, SvgPlugBroken } from "@opal/illustrations";
import { SvgAlertCircle, SvgPlus } from "@opal/icons";
import { PLUGIN_KIND_ICONS } from "@/lib/plugins/constants";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useInstalledPlugins } from "@/lib/plugins/hooks";
import { pluginDetailHref, withPluginSearchParams } from "@/lib/plugins/routes";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import PluginCard from "@/views/admin/PluginsPage/PluginCard";
import PluginAddCatalogModal, {
  type PluginCreation,
} from "@/views/admin/PluginsPage/components/PluginAddCatalogModal";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import CreateCustomAppModal from "@/views/admin/PluginsPage/components/CreateCustomAppModal";
import MCPPluginSetupModal from "@/views/admin/PluginsPage/components/mcp/MCPPluginSetupModal";
import OpenAPIPluginModal from "@/views/admin/PluginsPage/OpenAPIPluginModal";
import styles from "@/sections/plugins/PluginsPage.module.css";
import PluginDirectoryToolbar from "@/sections/plugins/PluginDirectoryToolbar";
import { useSettings } from "@/lib/settings/hooks";

const route = ADMIN_ROUTES.PLUGINS;

function PluginListError({
  title,
  onRetry,
  compact,
}: {
  title: string | RichStr;
  onRetry: () => void;
  compact: boolean;
}) {
  const t = useTranslations("actions.plugins");
  if (compact)
    return (
      <div
        role="alert"
        className="rounded-12 border border-border-01 bg-background-neutral-00 px-4 py-3"
      >
        <ContentAction
          icon={SvgAlertCircle}
          title={title}
          sizePreset="main-ui"
          variant="section"
          padding={0}
          rightChildren={
            <Button prominence="secondary" size="sm" onClick={onRetry}>
              {t("state.retry.label")}
            </Button>
          }
        />
      </div>
    );
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-2 rounded-16 border border-border-01 bg-background-neutral-00 px-4 py-6"
    >
      <IllustrationContent
        illustration={SvgPlugBroken}
        title={title}
        description={t("state.listErrorDescription")}
      />
      <Button prominence="secondary" onClick={onRetry}>
        {t("state.retry.label")}
      </Button>
    </div>
  );
}

function PluginRowsLoading() {
  const t = useTranslations("actions.plugins");
  return (
    <div
      role="status"
      aria-label={t("state.loading")}
      className="flex flex-col gap-2"
    >
      {[0, 1].map((index) => (
        <div key={index} className="flex min-w-0 items-center gap-3 py-3">
          <div className="opal-shimmer-block size-10 shrink-0 rounded-12" />
          <LineLoader lines={2} width="2/3" />
        </div>
      ))}
    </div>
  );
}

type PluginDialog =
  | { kind: "catalog"; catalogKind: "mcp" | "external-app" }
  | { kind: "create"; creation: PluginCreation }
  | null;

export default function PluginsPage() {
  const t = useTranslations("actions.plugins");
  const tSidebar = useTranslations("sidebar");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const { isGlobalHolder: fullAdmin } = usePermissionAuthority(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  const canManageActions = isGlobalHolder || isScopedManager;
  const settings = useSettings();
  const canManageApps = fullAdmin && settings.onyx_craft_available === true;
  const canCreate = canManageActions || canManageApps;
  const { plugins, mcp, openapi, externalApps } = useInstalledPlugins();
  const [dialog, setDialog] = useState<PluginDialog>(null);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"all" | "mcp" | "openapi" | "external-app">(
    "all"
  );
  const creation = dialog?.kind === "create" ? dialog.creation : null;
  const handledCreateQuery = useRef<string | null>(null);

  useEffect(() => {
    const add = searchParams.get("add");
    if (!add) {
      handledCreateQuery.current = null;
      return;
    }
    const currentQuery = searchParams.toString();
    if (
      !canCreate ||
      (add !== "mcp" && add !== "openapi" && add !== "external-app") ||
      (add === "external-app" ? !canManageApps : !canManageActions) ||
      handledCreateQuery.current === currentQuery
    )
      return;
    handledCreateQuery.current = currentQuery;
    setDialog({ kind: "create", creation: { kind: add } });
    const nextQuery = new URLSearchParams(currentQuery);
    nextQuery.delete("add");
    router.replace(
      withPluginSearchParams(ADMIN_ROUTES.PLUGINS.path, nextQuery)
    );
  }, [canCreate, canManageActions, canManageApps, router, searchParams]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredPlugins = plugins.filter((plugin) => {
    if (kind !== "all" && plugin.kind !== kind) return false;
    const text =
      plugin.kind === "mcp"
        ? `${plugin.server.name} ${plugin.server.description ?? ""} ${plugin.server.server_url}`
        : plugin.kind === "openapi"
          ? `${plugin.tool.name} ${plugin.tool.description}`
          : `${plugin.app.name} ${plugin.app.app_type} ${plugin.app.upstream_url_patterns.join(" ")}`;
    return text.toLowerCase().includes(normalizedQuery);
  });
  const installedEndpoints = new Set(
    plugins.flatMap((plugin) =>
      plugin.kind === "mcp"
        ? [plugin.server.server_url.replace(/\/+$/, "")]
        : []
    )
  );
  const isLoading =
    mcp.isLoading || openapi.isLoading || externalApps.isLoading;
  const hasError = mcp.hasError || openapi.hasError || externalApps.hasError;

  function addMenu() {
    return (
      <Dropdown align="end">
        <Dropdown.Trigger asChild>
          <Button icon={SvgPlus}>{t("add.label")}</Button>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("add.label")}
          items={[
            ...(canManageActions
              ? [
                  {
                    kind: "action" as const,
                    id: "mcp",
                    icon: PLUGIN_KIND_ICONS.mcp,
                    title: t("kind.mcp"),
                    onSelect: () =>
                      setDialog({ kind: "catalog", catalogKind: "mcp" }),
                  },
                  {
                    kind: "action" as const,
                    id: "openapi",
                    icon: PLUGIN_KIND_ICONS.openapi,
                    title: t("kind.openapi"),
                    onSelect: () =>
                      setDialog({
                        kind: "create",
                        creation: { kind: "openapi" },
                      }),
                  },
                ]
              : []),
            ...(canManageApps
              ? [
                  {
                    kind: "action" as const,
                    id: "external-app",
                    icon: PLUGIN_KIND_ICONS["external-app"],
                    title: t("kind.external-app"),
                    onSelect: () =>
                      setDialog({
                        kind: "catalog",
                        catalogKind: "external-app",
                      }),
                  },
                ]
              : []),
          ]}
        />
      </Dropdown>
    );
  }

  const kindOptions = ["all", "mcp", "openapi", "external-app"] as const;

  return (
    <div className={styles.directory}>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={t("title")}
          description={t("description")}
          stackActionsOnMobile
          actions={canCreate ? [<div key="add">{addMenu()}</div>] : []}
        />
        <SettingsLayouts.Body>
          <div className="flex flex-col gap-4">
            <PluginDirectoryToolbar
              searchLabel={t("search.placeholder")}
              query={query}
              onQueryChange={setQuery}
              filters={
                <Tabs
                  value={kind}
                  onValueChange={(value) => {
                    const next = kindOptions.find((option) => option === value);
                    if (next) setKind(next);
                  }}
                >
                  <Tabs.List aria-label={t("filters.label")}>
                    {kindOptions.map((value) => (
                      <Tabs.Trigger
                        key={value}
                        value={value}
                        // Apps need Craft and full admin: shown, not hidden,
                        // with the admin sidebar's upgrade tooltip.
                        disabled={value === "external-app" && !canManageApps}
                        tooltip={
                          value === "external-app" && !canManageApps
                            ? markdown(
                                tSidebar(
                                  "adminSidebar.businessOrEnterpriseOnly.tooltip"
                                )
                              )
                            : undefined
                        }
                      >
                        {value === "all"
                          ? t("filters.all")
                          : value === "external-app"
                            ? t("filters.apps")
                            : t(`kind.${value}`)}
                      </Tabs.Trigger>
                    ))}
                  </Tabs.List>
                </Tabs>
              }
            />
            {mcp.hasError && (
              <PluginListError
                compact={plugins.length > 0 || isLoading}
                title={t("state.mcpError")}
                onRetry={() => void mcp.refresh()}
              />
            )}
            {openapi.hasError && (
              <PluginListError
                compact={plugins.length > 0 || isLoading}
                title={t("state.openapiError")}
                onRetry={() => void openapi.refresh()}
              />
            )}
            {externalApps.hasError && (
              <PluginListError
                compact={plugins.length > 0 || isLoading}
                title={t("state.externalAppsError")}
                onRetry={() => void externalApps.refresh()}
              />
            )}
            {filteredPlugins.length > 0 && (
              <div className="flex flex-col gap-2">
                {filteredPlugins.map((plugin) => (
                  <PluginCard
                    key={`${plugin.kind}:${plugin.kind === "mcp" ? plugin.server.id : plugin.kind === "openapi" ? plugin.tool.id : plugin.app.id}`}
                    plugin={plugin}
                  />
                ))}
              </div>
            )}
            {isLoading && <PluginRowsLoading />}
            {!isLoading &&
              !hasError &&
              filteredPlugins.length === 0 &&
              (normalizedQuery ? (
                <div className="flex flex-col items-center py-8">
                  <SearchNoResults />
                </div>
              ) : plugins.length > 0 ? (
                <div className="flex flex-col items-center py-8">
                  <IllustrationContent
                    illustration={SvgEmpty}
                    title={t("state.noResults.title")}
                  />
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3 py-8">
                  <IllustrationContent
                    illustration={SvgEmpty}
                    title={t("state.empty.title")}
                    description={t("state.empty.description")}
                  />
                  {canCreate && addMenu()}
                </div>
              ))}
          </div>
        </SettingsLayouts.Body>
        {dialog?.kind === "catalog" && (
          <PluginAddCatalogModal
            catalogKind={dialog.catalogKind}
            onClose={() => setDialog(null)}
            onPick={(next) => {
              setDialog({ kind: "create", creation: next });
            }}
            canManageActions={canManageActions}
            installedEndpoints={installedEndpoints}
          />
        )}
        {creation?.kind === "external-app" &&
          canManageApps &&
          (creation.descriptor ? (
            <ConfigureProviderModal
              descriptor={creation.descriptor}
              existingApp={null}
              onClose={() => setDialog(null)}
              onSaved={() => void externalApps.refresh()}
            />
          ) : (
            <CreateCustomAppModal
              existingApp={null}
              onClose={() => setDialog(null)}
              onSaved={() => void externalApps.refresh()}
            />
          ))}
        {creation?.kind === "mcp" && (
          <MCPPluginSetupModal
            open
            onClose={() => {
              setDialog(null);
              void mcp.refresh();
            }}
            initialUrl={creation.suggestion?.serverUrl}
            initialName={creation.suggestion?.name}
            setupGuide={
              creation.suggestion
                ? {
                    url: creation.suggestion.docsUrl,
                    description: t(
                      `catalog.${creation.suggestion.id}.description`
                    ),
                    note:
                      creation.suggestion.id === "atlassian"
                        ? t("catalog.atlassian.approvalNote")
                        : undefined,
                  }
                : undefined
            }
            onCompleted={(server) => {
              setDialog(null);
              void mcp.refresh();
              router.push(pluginDetailHref({ kind: "mcp", id: server.id }));
            }}
          />
        )}
        {creation?.kind === "openapi" && (
          <OpenAPIPluginModal
            onClose={() => setDialog(null)}
            onCreated={(toolId) => {
              setDialog(null);
              void openapi.refresh();
              router.push(pluginDetailHref({ kind: "openapi", id: toolId }));
            }}
          />
        )}
      </SettingsLayouts.Root>
    </div>
  );
}
