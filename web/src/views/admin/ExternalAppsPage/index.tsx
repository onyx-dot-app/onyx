"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Button, Card, Tabs, Text } from "@opal/components";
import { IllustrationContent, SettingsLayouts } from "@opal/layouts";
import { SvgUnPlugged } from "@opal/illustrations";
import { SvgArrowLeft, SvgPlus, SvgSettings } from "@opal/icons";
import { MCPServer, MCPServersResponse } from "@/lib/tools/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  availableBuiltInDescriptors,
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import AddAppCatalogModal from "@/app/craft/v1/apps/admin/AddAppCatalogModal";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import McpServerPolicyModal from "@/app/craft/v1/apps/admin/McpServerPolicyModal";
import {
  ConnectableKind,
  KIND_ORDER,
  parseConnectableTab,
  useConnectableTab,
} from "@/app/craft/v1/apps/connectableApps";
import { compareByName } from "@/lib/skills/picker";
import { ConfiguredIntegration } from "@/views/admin/ExternalAppsPage/interfaces";
import {
  externalAppToIntegration,
  mcpServerToIntegration,
} from "@/views/admin/ExternalAppsPage/integrations";
import IntegrationCard from "@/views/admin/ExternalAppsPage/IntegrationCard";

interface ModalState {
  descriptor: BuiltInExternalAppDescriptor;
  existingApp: ExternalAppAdminResponse | null;
}

// Apps and MCP servers are configured and governed differently, so each kind
// gets its own tab — mirroring the member-facing Apps page.
const KIND_COPY: Record<
  ConnectableKind,
  { label: string; blurb: string; emptyTitle: string; empty: string }
> = {
  app: {
    label: "Apps",
    blurb:
      "Configured once for the whole organization. Edit an app to set shared credentials, action policies, and associated skills.",
    emptyTitle: "No apps yet",
    empty: "Add an app to make it available to everyone in your organization.",
  },
  mcp: {
    label: "MCP servers",
    blurb:
      "Enable a server to let members with access to it use its tools in Craft. Edit it to set each tool's approval policy. Server connections and access are managed in Actions.",
    emptyTitle: "No MCP servers yet",
    empty:
      "Connect a server in Actions, then enable it here for your organization.",
  },
};

// Admin external-apps management; members connect their own accounts on the
// Apps page. One list governs everything granted to the Craft agent — external
// apps and MCP servers — and the "Add app" catalog is the single entry point
// for granting more.
export default function ExternalAppsPage() {
  const [catalogOpen, setCatalogOpen] = useState(false);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={ADMIN_ROUTES.CRAFT_APPS.icon}
        title={ADMIN_ROUTES.CRAFT_APPS.title}
        description="Set up the apps your organization's Craft agent can use. Each member connects their own account on Craft's Apps page."
        rightChildren={
          <div className="flex items-center gap-2">
            <Button
              href="/craft/v1/apps"
              prominence="secondary"
              icon={SvgArrowLeft}
            >
              Back to Craft
            </Button>
            <Button icon={SvgPlus} onClick={() => setCatalogOpen(true)}>
              Add app
            </Button>
          </div>
        }
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
  const router = useRouter();
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
  const [editServer, setEditServer] = useState<MCPServer | null>(null);
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
  const activeCustomModal =
    customModal ??
    (deepLinkedApp?.app_type === "CUSTOM"
      ? { existingApp: deepLinkedApp }
      : null);
  const activeProviderModal =
    modalState ??
    (deepLinkedApp && deepLinkedDescriptor
      ? { descriptor: deepLinkedDescriptor, existingApp: deepLinkedApp }
      : null);

  function closeAppModal() {
    setCustomModal(null);
    setModalState(null);
    if (deepLinkedAppId) {
      setDismissedDeepLink(deepLinkedAppId);
      router.replace("/admin/craft/apps" as Route);
    }
  }

  // Both kinds govern through the same row; only where the data comes from —
  // and which edit dialog opens — differs.
  const byKind = useMemo<Record<ConnectableKind, ConfiguredIntegration[]>>(
    () => ({
      app: (apps ?? [])
        .map((app) =>
          externalAppToIntegration(app, descriptorByAppType.get(app.app_type), {
            onEdit: (descriptor) =>
              setModalState({ descriptor, existingApp: app }),
            onEditCustom: (customApp) =>
              setCustomModal({ existingApp: customApp }),
            onChange: async () => {
              await mutateApps();
            },
          })
        )
        .sort(compareByName),
      mcp: (mcpData?.mcp_servers ?? [])
        .map((server) =>
          mcpServerToIntegration(server, {
            onEdit: () => setEditServer(server),
            onChange: async () => {
              await mutateMcp();
            },
          })
        )
        .sort(compareByName),
    }),
    [apps, mcpData, descriptorByAppType, mutateApps, mutateMcp]
  );

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
          Add app
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
          Manage in Actions
        </Button>
      ),
      emptyAction: (
        <Button href={ADMIN_ROUTES.MCP_ACTIONS.path} icon={SvgSettings}>
          Open Actions
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
                ? `${KIND_COPY[kind].label} · ${byKind[kind].length}`
                : KIND_COPY[kind].label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {KIND_ORDER.map((kind) => (
          <Tabs.Content key={kind} value={kind}>
            {panels[kind].ready ? (
              <IntegrationPanel
                kind={kind}
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
          onSaved={() => mutateApps()}
          descriptor={activeProviderModal.descriptor}
          existingApp={activeProviderModal.existingApp}
        />
      )}

      {activeCustomModal && (
        <CreateCustomAppModal
          key={activeCustomModal.existingApp?.id ?? "new"}
          onClose={closeAppModal}
          onSaved={() => mutateApps()}
          existingApp={activeCustomModal.existingApp}
        />
      )}

      {editServer && (
        <McpServerPolicyModal
          key={editServer.id}
          onClose={() => setEditServer(null)}
          onSaved={() => mutateMcp()}
          server={editServer}
        />
      )}
    </div>
  );
}

function LoadingCard() {
  return (
    <Card background="none" border="dashed" rounding={4}>
      <Text font="main-content-body">Loading…</Text>
    </Card>
  );
}

interface IntegrationPanelProps {
  kind: ConnectableKind;
  integrations: ConfiguredIntegration[];
  /** Kind-appropriate affordance beside the blurb (e.g. MCP's Actions link). */
  blurbAction?: React.ReactNode;
  /** Call to action under the kind's empty state. */
  emptyAction?: React.ReactNode;
}

function IntegrationPanel({
  kind,
  integrations,
  blurbAction,
  emptyAction,
}: IntegrationPanelProps) {
  const copy = KIND_COPY[kind];

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
      {integrations.map((integration) => (
        <IntegrationCard key={integration.key} integration={integration} />
      ))}
    </div>
  );
}
