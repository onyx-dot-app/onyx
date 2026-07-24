"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { IconFunctionComponent } from "@opal/types";
import { Button, Divider, Text } from "@opal/components";
import { ConfirmationModalLayout, SettingsLayouts, toast } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import {
  SvgArrowLeft,
  SvgPlug,
  SvgPlus,
  SvgSettings,
  SvgTrash,
} from "@opal/icons";
import { MCPServer, MCPServersResponse } from "@/lib/tools/interfaces";
import { updateMCPServer } from "@/lib/tools/mcpService";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  availableBuiltInDescriptors,
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import McpServerPolicyModal from "@/app/craft/v1/apps/admin/McpServerPolicyModal";
import {
  deleteExternalApp,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";

interface ModalState {
  descriptor: BuiltInExternalAppDescriptor;
  existingApp: ExternalAppAdminResponse | null;
}

// Admin External Apps management; members connect their own accounts on the Apps page.
export default function ExternalAppsPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={ADMIN_ROUTES.CRAFT_APPS.icon}
        title={ADMIN_ROUTES.CRAFT_APPS.title}
        description="Connect third-party integrations so users in your org can authorize them with their personal accounts in Onyx Craft."
        rightChildren={
          <Button
            href="/craft/v1/apps"
            prominence="secondary"
            icon={SvgArrowLeft}
          >
            Back to Craft
          </Button>
        }
      />
      <SettingsLayouts.Body>
        <AppsAdminContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

function AppsAdminContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: descriptors } = useSWR<BuiltInExternalAppDescriptor[]>(
    SWR_KEYS.buildExternalAppsBuiltInOptions,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const {
    data: apps,
    mutate: mutateApps,
    isValidating: appsValidating,
  } = useSWR<ExternalAppAdminResponse[]>(
    SWR_KEYS.buildExternalAppsAdmin,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );

  const [modalState, setModalState] = useState<ModalState | null>(null);
  // Custom-app create/edit modal. `existingApp: null` → create; non-null → edit.
  const [customModal, setCustomModal] = useState<{
    existingApp: ExternalAppAdminResponse | null;
  } | null>(null);
  const [dismissedDeepLink, setDismissedDeepLink] = useState<string | null>(
    null
  );

  const isReady = descriptors !== undefined && apps !== undefined;
  const hasConfigured = isReady && apps.length > 0;

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

  // Already-configured providers drop off the available list (one per provider).
  const availableDescriptors = availableBuiltInDescriptors(
    descriptors ?? [],
    apps ?? []
  );

  const deepLinkedAppId = searchParams.get("editAppId");
  const deepLinkedApp =
    !appsValidating &&
    deepLinkedAppId !== null &&
    deepLinkedAppId !== dismissedDeepLink
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

  if (!isReady) {
    return (
      <Card variant="tertiary">
        <Text font="main-content-body">Loading…</Text>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {hasConfigured && (
        <>
          <section className="flex flex-col gap-2">
            <Text font="main-content-emphasis" color="text-04">
              Configured
            </Text>
            <div className="flex flex-col gap-2">
              {apps.map((app) => (
                <IntegrationCard
                  key={app.id}
                  integration={externalAppToIntegration(
                    app,
                    descriptorByAppType.get(app.app_type) ?? null,
                    {
                      onEdit: (descriptor) =>
                        setModalState({ descriptor, existingApp: app }),
                      onEditCustom: (customApp) =>
                        setCustomModal({ existingApp: customApp }),
                      onChange: () => mutateApps(),
                    }
                  )}
                />
              ))}
            </div>
          </section>

          <Divider />
        </>
      )}

      <McpServersSection />

      <section className="flex flex-col gap-2">
        <Text font="main-content-emphasis" color="text-04">
          {hasConfigured ? "Add another" : "Available apps"}
        </Text>
        <Text font="secondary-body" color="text-03">
          Add a built-in integration. Each provider can be configured once;
          connected providers no longer appear here. Use a custom app for
          anything not listed.
        </Text>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
          {availableDescriptors.map((descriptor) => (
            <AvailableAppCard
              key={descriptor.app_type}
              descriptor={descriptor}
              onClick={() => setModalState({ descriptor, existingApp: null })}
            />
          ))}
          <CreateCustomAppCard
            onClick={() => setCustomModal({ existingApp: null })}
          />
        </div>
      </section>

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
    </div>
  );
}

// ── MCP servers ────────────────────────────────────────────────────────
//
// Every configured MCP server, rendered through the same card as the
// external apps above. Enable/Disable controls Craft availability; Edit
// opens the per-tool policy dialog. New servers are added on the MCP
// actions page.
function McpServersSection() {
  const { data, mutate } = useSWR<MCPServersResponse>(
    SWR_KEYS.adminMcpServers,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const [editServer, setEditServer] = useState<MCPServer | null>(null);
  const servers = data?.mcp_servers ?? [];
  if (servers.length === 0) return null;

  return (
    <>
      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <Text font="main-content-emphasis" color="text-04">
            MCP servers
          </Text>
          <Button
            href="/admin/actions/mcp"
            prominence="tertiary"
            icon={SvgSettings}
          >
            Manage in Actions
          </Button>
        </div>
        <Text font="secondary-body" color="text-03">
          Enable an MCP server to let the Craft agent use its tools; enabled
          servers appear alongside apps on the Apps page. Edit a server to set
          each tool&apos;s approval policy.
        </Text>
        <div className="flex flex-col gap-2">
          {servers.map((server) => (
            <IntegrationCard
              key={server.id}
              integration={mcpServerToIntegration(server, {
                onEdit: () => setEditServer(server),
                onChange: () => mutate(),
              })}
            />
          ))}
        </div>
      </section>

      {editServer && (
        <McpServerPolicyModal
          key={editServer.id}
          onClose={() => setEditServer(null)}
          onSaved={() => mutate()}
          server={editServer}
        />
      )}
    </>
  );
}

// ── Configured integrations ────────────────────────────────────────────
//
// Normalized admin view of anything already granted to the Craft agent.
// External apps and MCP servers map into this shape upstream, so both render
// and behave through the same card — only where the data comes from differs.
interface ConfiguredIntegration {
  logo: IconFunctionComponent;
  name: string;
  statusText: string;
  enabled: boolean;
  toggleEnabled: () => Promise<void>;
  /** Null → no Edit button (e.g. orphaned app types). */
  edit: (() => void) | null;
  /** Null → not deletable (MCP servers, Onyx-managed apps). */
  remove: {
    run: () => Promise<void>;
    retainedSkillCount: number;
  } | null;
}

interface ExternalAppHandlers {
  /** Edit a built-in provider instance (driven by its descriptor). */
  onEdit: (descriptor: BuiltInExternalAppDescriptor) => void;
  /** Edit a custom app (no descriptor — config is on the row itself). */
  onEditCustom: (app: ExternalAppAdminResponse) => void;
  onChange: () => Promise<unknown>;
}

function externalAppToIntegration(
  app: ExternalAppAdminResponse,
  /** Null when the app's app_type no longer has a backend descriptor. */
  descriptor: BuiltInExternalAppDescriptor | null,
  { onEdit, onEditCustom, onChange }: ExternalAppHandlers
): ConfiguredIntegration {
  return {
    logo: getAppTypeLogo(app.app_type),
    name: app.name,
    statusText: app.enabled
      ? "Users connect this app from the Apps page"
      : "Disabled — unavailable to users",
    enabled: app.enabled,
    toggleEnabled: async () => {
      await updateExternalApp(app.id, { enabled: !app.enabled });
      await onChange();
    },
    // Edit only works for custom apps and built-ins whose descriptor still
    // exists; orphan app_types can only be disabled/deleted.
    edit:
      app.app_type === "CUSTOM"
        ? () => onEditCustom(app)
        : descriptor
          ? () => onEdit(descriptor)
          : null,
    // Onyx-managed built-ins are provisioned by Onyx.
    remove: app.is_onyx_managed
      ? null
      : {
          retainedSkillCount: app.associated_skills.length,
          run: async () => {
            await deleteExternalApp(app.id);
            await onChange();
          },
        },
  };
}

interface McpServerHandlers {
  onEdit: () => void;
  onChange: () => Promise<unknown>;
}

function mcpServerToIntegration(
  server: MCPServer,
  { onEdit, onChange }: McpServerHandlers
): ConfiguredIntegration {
  const enabled = server.available_in_craft ?? false;
  return {
    logo: getActionIcon(server.server_url, server.name),
    name: server.name,
    statusText: enabled
      ? "Available to the Craft agent — tool calls follow their approval policies"
      : "Disabled — unavailable to the Craft agent",
    enabled,
    toggleEnabled: async () => {
      await updateMCPServer(server.id, { available_in_craft: !enabled });
      await onChange();
    },
    edit: onEdit,
    remove: null,
  };
}

// ── Configured-integration card ────────────────────────────────────────

interface IntegrationCardProps {
  integration: ConfiguredIntegration;
}

function IntegrationCard({ integration }: IntegrationCardProps) {
  const {
    logo: Logo,
    name,
    statusText,
    enabled,
    toggleEnabled,
    edit,
    remove,
  } = integration;
  const [isMutating, setIsMutating] = useState(false);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);

  async function run(
    action: () => Promise<void>,
    failureMessage: string
  ): Promise<boolean> {
    setIsMutating(true);
    try {
      await action();
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : failureMessage);
      return false;
    } finally {
      setIsMutating(false);
    }
  }

  return (
    <Card>
      <div className="flex items-center gap-3 w-full">
        <Logo className="w-8 h-8" />
        <div className="flex-1 flex flex-col gap-0.5">
          <Text font="main-ui-action">{name}</Text>
          <Text font="secondary-body" color="text-03">
            {statusText}
          </Text>
        </div>
        <div className="flex items-center gap-2">
          {edit && (
            <Button prominence="secondary" onClick={edit} disabled={isMutating}>
              Edit
            </Button>
          )}
          <Button
            prominence="secondary"
            onClick={() =>
              run(
                toggleEnabled,
                `Failed to ${enabled ? "disable" : "enable"} "${name}"`
              )
            }
            disabled={isMutating}
          >
            {enabled ? "Disable" : "Enable"}
          </Button>
          {remove && (
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgTrash}
              onClick={() => setConfirmingRemoval(true)}
              disabled={isMutating}
              aria-label={`Delete ${name}`}
            />
          )}
        </div>
      </div>
      {confirmingRemoval && remove && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={`Delete “${name}”?`}
          description="This deletes the app configuration and connection data."
          onClose={isMutating ? undefined : () => setConfirmingRemoval(false)}
          submit={
            <Button
              variant="danger"
              disabled={isMutating}
              onClick={async () => {
                if (await run(remove.run, `Failed to delete "${name}"`)) {
                  setConfirmingRemoval(false);
                }
              }}
            >
              {isMutating ? "Deleting…" : "Delete app"}
            </Button>
          }
        >
          {remove.retainedSkillCount === 0
            ? "No skills will be deleted."
            : `${remove.retainedSkillCount} associated ${
                remove.retainedSkillCount === 1 ? "skill" : "skills"
              } will be kept, unlinked from this app, and disabled for everyone.`}
        </ConfirmationModalLayout>
      )}
    </Card>
  );
}

// ── Available app card ────────────────────────────────────────────────

interface AvailableAppCardProps {
  descriptor: BuiltInExternalAppDescriptor;
  onClick: () => void;
}

function AvailableAppCard({ descriptor, onClick }: AvailableAppCardProps) {
  const Logo = getAppTypeLogo(descriptor.app_type);
  return (
    <Card className="h-full flex flex-col justify-center">
      <div className="flex items-center gap-3 w-full">
        <Logo className="w-8 h-8 shrink-0" />
        <div className="flex-1">
          <Text font="main-ui-action">{descriptor.name}</Text>
        </div>
        <Button icon={SvgPlus} onClick={onClick}>
          Add
        </Button>
      </div>
    </Card>
  );
}

// ── Create-custom-app card ────────────────────────────────────────────

interface CreateCustomAppCardProps {
  onClick: () => void;
}

function CreateCustomAppCard({ onClick }: CreateCustomAppCardProps) {
  return (
    <Card className="h-full flex flex-col justify-center">
      <div className="flex items-center gap-3 w-full">
        <SvgPlug className="w-8 h-8 shrink-0" />
        <div className="flex-1 flex flex-col gap-0.5">
          <Text font="main-ui-action">Custom app</Text>
          <Text font="secondary-body" color="text-03">
            Configure credentials and network access for your own integration.
          </Text>
        </div>
        <Button icon={SvgPlus} onClick={onClick}>
          Create
        </Button>
      </div>
    </Card>
  );
}
