"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Button, Card, Tabs, Text } from "@opal/components";
import { IllustrationContent, SettingsLayouts } from "@opal/layouts";
import { SvgUnPlugged } from "@opal/illustrations";
import { SvgArrowLeft, SvgPlus, SvgSettings } from "@opal/icons";
import { MCPServersResponse } from "@/lib/mcp/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  availableBuiltInDescriptors,
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import AddAppCatalogModal from "@/app/craft/v1/apps/admin/AddAppCatalogModal";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import McpServerDialogs from "@/sections/actions/McpServerDialogs";
import OpenApiActionEditor from "@/sections/actions/OpenApiActionEditor";
import OpenApiAppPolicyModal from "@/app/craft/v1/apps/admin/OpenApiAppPolicyModal";
import McpServerPolicyModal from "@/app/craft/v1/apps/admin/McpServerPolicyModal";
import {
  ConnectableKind,
  KIND_ORDER,
  parseConnectableTab,
  useConnectableTab,
} from "@/app/craft/v1/apps/connectableApps";
import { compareByName } from "@/lib/skills/picker";
import { ConfiguredIntegration } from "@/views/admin/ExternalAppsPage/types";
import {
  externalAppToIntegration,
  type IntegrationLabels,
  mcpServerToIntegration,
} from "@/views/admin/ExternalAppsPage/integrations";
import IntegrationCard from "@/views/admin/ExternalAppsPage/IntegrationCard";

interface SourceEditorSelection {
  kind:
    | "openapi-configuration"
    | "openapi-permissions"
    | "mcp-configuration"
    | "mcp-permissions";
  id: number;
}

interface ModalState {
  mode?: "configuration" | "permissions";
  descriptor: BuiltInExternalAppDescriptor;
  existingApp: ExternalAppAdminResponse | null;
}

// Apps and MCP servers are configured and governed differently, so each kind
// gets its own tab — mirroring the member-facing Apps page.
interface KindCopy {
  label: string;
  labelWithCount: (count: number) => string;
  blurb: string;
  emptyTitle: string;
  empty: string;
}

// Admin external-apps management; members connect their own accounts on the
// Apps page. One list governs everything granted to the Craft agent — external
// apps and MCP servers — and the "Add app" catalog is the single entry point
// for granting more.
export default function ExternalAppsPage() {
  const t = useTranslations("admin.externalApps");
  const adminRouteTitle = useAdminRouteTitle();
  const [catalogOpen, setCatalogOpen] = useState(false);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={ADMIN_ROUTES.CRAFT_APPS.icon}
        title={adminRouteTitle(ADMIN_ROUTES.CRAFT_APPS)}
        description={t("page.description")}
        actions={[
          <div key="primary" className="flex items-center gap-2">
            <Button
              href="/craft/v1/apps"
              prominence="secondary"
              icon={SvgArrowLeft}
            >
              {t("page.backToCraftButton.label")}
            </Button>
            <Button icon={SvgPlus} onClick={() => setCatalogOpen(true)}>
              {t("page.addAppButton.label")}
            </Button>
          </div>,
        ]}
      />
      <SettingsLayouts.Body>
        <AppsAdminContent
          catalogOpen={catalogOpen}
          onCatalogOpenChange={setCatalogOpen}
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

interface AppsAdminContentProps {
  catalogOpen: boolean;
  onCatalogOpenChange: (open: boolean) => void;
}

function AppsAdminContent({
  catalogOpen,
  onCatalogOpenChange,
}: AppsAdminContentProps) {
  const t = useTranslations("admin.externalApps");
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const searchParams = useSearchParams();
  const { data: descriptors } = useSWR<BuiltInExternalAppDescriptor[]>(
    SWR_KEYS.buildExternalAppsBuiltInOptions,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const { data: apps, mutate: mutateApps } = useSWR<ExternalAppAdminResponse[]>(
    SWR_KEYS.buildExternalAppsAdmin,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const { data: mcpData, mutate: mutateMcp } = useSWR<MCPServersResponse>(
    SWR_KEYS.adminMcpServers,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );

  const [tab, setTab] = useConnectableTab();
  const [modalState, setModalState] = useState<ModalState | null>(null);
  // Custom-app create/edit modal. `existingApp: null` → create; non-null → edit.
  const [customModal, setCustomModal] = useState<{
    existingApp: ExternalAppAdminResponse | null;
  } | null>(null);
  const [sourceEditor, setSourceEditor] =
    useState<SourceEditorSelection | null>(null);
  const [dismissedDeepLink, setDismissedDeepLink] = useState<string | null>(
    null
  );

  // Only the app fetches gate the page — a slow MCP request must not block
  // app management. The MCP tab shows its own loading card while pending so
  // it never reads as a false "No MCP servers yet".
  const isReady = descriptors !== undefined && apps !== undefined;

  // Edit only works for apps whose app_type still has a descriptor. Apps with
  // an orphan app_type still render but can only be disabled/deleted.
  const descriptorByAppType = useMemo(
    () =>
      new Map<string, BuiltInExternalAppDescriptor>(
        (descriptors ?? []).map((descriptor) => [
          descriptor.app_type,
          descriptor,
        ])
      ),
    [descriptors]
  );

  const deepLinkedAppId = searchParams.get("editAppId");
  const deepLinkedApp =
    deepLinkedAppId !== null && deepLinkedAppId !== dismissedDeepLink
      ? apps?.find((app) => app.id === Number(deepLinkedAppId))
      : undefined;
  const deepLinkedDescriptor = deepLinkedApp
    ? descriptorByAppType.get(deepLinkedApp.app_type)
    : undefined;
  const selectedServer = mcpData?.mcp_servers.find(
    (server) => server.id === sourceEditor?.id
  );
  const selectedApp = apps?.find((app) => app.id === sourceEditor?.id);
  const activeCustomModal =
    customModal ??
    (deepLinkedApp?.app_type === "CUSTOM" &&
    deepLinkedApp.openapi_tool_id == null
      ? { existingApp: deepLinkedApp }
      : null);
  const activeProviderModal =
    modalState ??
    (deepLinkedApp && deepLinkedDescriptor
      ? {
          descriptor: deepLinkedDescriptor,
          existingApp: deepLinkedApp,
          mode: "configuration" as const,
        }
      : null);

  function closeAppModal() {
    setCustomModal(null);
    setModalState(null);
    if (deepLinkedAppId) {
      setDismissedDeepLink(deepLinkedAppId);
      router.replace("/admin/craft/apps");
    }
  }

  const integrationLabels = useMemo<IntegrationLabels>(
    () => ({
      providedByOnyx: t("facts.providedByOnyx"),
      noCredentials: t("facts.noCredentials"),
      orgCredentialsSet: t("facts.orgCredentialsSet"),
      perUserCredentials: t("facts.perUserCredentials"),
      noCustomSkills: t("facts.noCustomSkills"),
      invalidSkill: t("warnings.invalidSkill"),
      providerUnavailable: t("warnings.providerUnavailable"),
      sourceActionDisabled: t("warnings.sourceActionDisabled"),
      openApiAction: t("facts.openApiAction"),
      editAction: t("card.editAction.label"),
      editPermissions: t("card.editPermissions.label"),
      manageOpenApi: t("card.manageOpenApi.label"),
      manageBuiltIn: t("card.manageBuiltIn.label"),
      manageMcp: t("card.manageMcp.label"),
      upstreamPatternCount: (count) => t("facts.upstreamPatterns", { count }),
      actionCount: (count) => t("facts.actions", { count }),
      customSkillCount: (count) => t("facts.customSkills", { count }),
      toolCount: (count) => t("facts.tools", { count }),
    }),
    [t]
  );

  // Both kinds govern through the same row; only where the data comes from —
  // and which edit dialog opens — differs.
  const byKind = useMemo<Record<ConnectableKind, ConfiguredIntegration[]>>(
    () => ({
      app: (apps ?? [])
        .map((app) =>
          externalAppToIntegration(
            app,
            descriptorByAppType.get(app.app_type),
            {
              onEdit: (descriptor, mode) =>
                setModalState({ descriptor, existingApp: app, mode }),
              onManageOpenApi: (app) =>
                setSourceEditor({ kind: "openapi-configuration", id: app.id }),
              onEditCustom: (customApp) => {
                if (customApp.openapi_tool_id != null) {
                  setSourceEditor({
                    kind: "openapi-permissions",
                    id: customApp.id,
                  });
                } else {
                  setCustomModal({ existingApp: customApp });
                }
              },
              onChange: async () => {
                await Promise.all([
                  mutateApps(),
                  ...(app.openapi_tool_id != null
                    ? [mutate(SWR_KEYS.openApiTools)]
                    : []),
                ]);
              },
            },
            integrationLabels
          )
        )
        .sort(compareByName),
      mcp: (mcpData?.mcp_servers ?? [])
        .map((server) =>
          mcpServerToIntegration(
            server,
            {
              onEdit: () =>
                setSourceEditor({ kind: "mcp-permissions", id: server.id }),
              onManage: () =>
                setSourceEditor({ kind: "mcp-configuration", id: server.id }),
              onChange: async () => {
                await mutateMcp();
              },
            },
            integrationLabels
          )
        )
        .sort(compareByName),
    }),
    [
      apps,
      mcpData,
      descriptorByAppType,
      mutateApps,
      mutate,
      mutateMcp,
      integrationLabels,
    ]
  );

  const kindCopy: Record<ConnectableKind, KindCopy> = {
    app: {
      label: t("apps.tab.label"),
      labelWithCount: (count) => t("apps.tab.labelWithCount", { count }),
      blurb: t("apps.panel.blurb"),
      emptyTitle: t("apps.empty.title"),
      empty: t("apps.empty.description"),
    },
    mcp: {
      label: t("mcpServers.tab.label"),
      labelWithCount: (count) => t("mcpServers.tab.labelWithCount", { count }),
      blurb: t("mcpServers.panel.blurb"),
      emptyTitle: t("mcpServers.empty.title"),
      empty: t("mcpServers.empty.description"),
    },
  };

  // Per-kind pieces the shared panel can't own: data readiness (the app
  // fetches gate the whole page; MCP resolves on its own) and actions.
  const panels: Record<
    ConnectableKind,
    {
      ready: boolean;
      blurbAction?: React.ReactNode;
      emptyAction?: React.ReactNode;
    }
  > = {
    app: {
      ready: true,
      emptyAction: (
        <Button icon={SvgPlus} onClick={() => onCatalogOpenChange(true)}>
          {t("apps.empty.addButton.label")}
        </Button>
      ),
    },
    mcp: {
      ready: mcpData !== undefined,
      blurbAction: (
        <Button
          prominence="tertiary"
          href={ADMIN_ROUTES.MCP_ACTIONS.path}
          icon={SvgSettings}
        >
          {t("mcpServers.manageInActionsButton.label")}
        </Button>
      ),
      emptyAction: (
        <Button href={ADMIN_ROUTES.MCP_ACTIONS.path} icon={SvgSettings}>
          {t("mcpServers.empty.openActionsButton.label")}
        </Button>
      ),
    },
  };

  if (!isReady) {
    return <LoadingCard />;
  }

  return (
    <div className="flex flex-col gap-2">
      <Tabs
        value={tab}
        onValueChange={(next) => setTab(parseConnectableTab(next))}
      >
        <Tabs.List>
          {KIND_ORDER.map((kind) => (
            <Tabs.Trigger key={kind} value={kind}>
              {/* No count until the kind's data resolves — "· 0" would lie. */}
              {panels[kind].ready
                ? kindCopy[kind].labelWithCount(byKind[kind].length)
                : kindCopy[kind].label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {KIND_ORDER.map((kind) => (
          <Tabs.Content key={kind} value={kind}>
            {panels[kind].ready ? (
              <IntegrationPanel
                copy={kindCopy[kind]}
                integrations={byKind[kind]}
                blurbAction={panels[kind].blurbAction}
                emptyAction={panels[kind].emptyAction}
              />
            ) : (
              <LoadingCard />
            )}
          </Tabs.Content>
        ))}
      </Tabs>

      {catalogOpen && (
        <AddAppCatalogModal
          onClose={() => onCatalogOpenChange(false)}
          // Already-configured providers drop off the catalog (one per provider).
          descriptors={availableBuiltInDescriptors(
            descriptors ?? [],
            apps ?? []
          )}
          onPickProvider={(descriptor) => {
            onCatalogOpenChange(false);
            setModalState({ descriptor, existingApp: null });
          }}
          onPickCustom={() => {
            onCatalogOpenChange(false);
            setCustomModal({ existingApp: null });
          }}
        />
      )}

      {activeProviderModal && (
        <ConfigureProviderModal
          key={
            activeProviderModal.existingApp?.id ??
            activeProviderModal.descriptor.app_type
          }
          onClose={closeAppModal}
          onSaved={async () => {
            await mutateApps();
          }}
          mode={activeProviderModal.mode}
          descriptor={activeProviderModal.descriptor}
          existingApp={activeProviderModal.existingApp}
        />
      )}

      {activeCustomModal && (
        <CreateCustomAppModal
          key={activeCustomModal.existingApp?.id ?? "new"}
          onClose={closeAppModal}
          onSaved={async () => {
            await mutateApps();
          }}
          existingApp={activeCustomModal.existingApp}
        />
      )}

      {sourceEditor?.kind === "openapi-permissions" && selectedApp && (
        <OpenApiAppPolicyModal
          key={selectedApp.id}
          app={selectedApp}
          onClose={() => setSourceEditor(null)}
          onChanged={async () => {
            await mutateApps();
          }}
        />
      )}
      {sourceEditor?.kind === "openapi-configuration" &&
        selectedApp?.openapi_tool_id != null && (
          <OpenApiActionEditor
            key={selectedApp.id}
            toolId={selectedApp.openapi_tool_id}
            name={selectedApp.name}
            onClose={() => setSourceEditor(null)}
            onChanged={async () => {
              await mutateApps();
            }}
          />
        )}
      {sourceEditor?.kind === "mcp-configuration" && selectedServer && (
        <McpServerDialogs
          servers={mcpData?.mcp_servers ?? []}
          initialServer={selectedServer}
          onClosed={() => setSourceEditor(null)}
          onChanged={async () => {
            await mutateMcp();
          }}
        />
      )}
      {sourceEditor?.kind === "mcp-permissions" && selectedServer && (
        <McpServerPolicyModal
          key={selectedServer.id}
          server={selectedServer}
          onClose={() => setSourceEditor(null)}
          onSaved={async () => {
            await mutateMcp();
          }}
        />
      )}
    </div>
  );
}

function LoadingCard() {
  const t = useTranslations("admin.externalApps");
  return (
    <Card color="transparent" border="dashed" rounding={4}>
      <Text font="main-content-body">{t("loading.label")}</Text>
    </Card>
  );
}

interface IntegrationPanelProps {
  copy: KindCopy;
  integrations: ConfiguredIntegration[];
  /** Kind-appropriate affordance beside the blurb (e.g. MCP's Actions link). */
  blurbAction?: React.ReactNode;
  /** Call to action under the kind's empty state. */
  emptyAction?: React.ReactNode;
}

function IntegrationPanel({
  copy,
  integrations,
  blurbAction,
  emptyAction,
}: IntegrationPanelProps) {
  if (integrations.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 pt-2">
        <IllustrationContent
          illustration={SvgUnPlugged}
          title={copy.emptyTitle}
          description={copy.empty}
        />
        {emptyAction}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2 pb-2">
        <Text font="secondary-body" color="text-03">
          {copy.blurb}
        </Text>
        {blurbAction}
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
        {integrations.map((integration) => (
          <IntegrationCard key={integration.key} integration={integration} />
        ))}
      </div>
    </div>
  );
}
