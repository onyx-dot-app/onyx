"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, Modal, Text } from "@opal/components";
import { SvgPlug, SvgServer } from "@opal/icons";
import { LineLoader } from "@opal/loaders";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  availableBuiltInDescriptors,
  getAppTypeLogo,
  type BuiltInExternalAppDescriptor,
  type ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import {
  SUGGESTED_MCP_PLUGINS,
  type SuggestedMCPPlugin,
} from "@/lib/plugins/catalog";
import PluginCatalogCard from "@/sections/plugins/PluginCatalogCard";

export type PluginCreation =
  | { kind: "mcp"; suggestion?: SuggestedMCPPlugin }
  | { kind: "openapi" }
  | { kind: "external-app"; descriptor?: BuiltInExternalAppDescriptor };

interface PluginAddCatalogModalProps {
  onClose: () => void;
  onPick: (creation: PluginCreation) => void;
  installedEndpoints: Set<string>;
  canManageActions: boolean;
  catalogKind: "mcp" | "external-app";
}

export default function PluginAddCatalogModal({
  onClose,
  onPick,
  installedEndpoints,
  canManageActions,
  catalogKind,
}: PluginAddCatalogModalProps) {
  const t = useTranslations("actions.plugins");
  const tApps = useTranslations("craft.apps.addCatalog");
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  const canLoadApps = isGlobalHolder && catalogKind === "external-app";
  const apps = useSWR<ExternalAppAdminResponse[], Error>(
    canLoadApps ? SWR_KEYS.buildExternalAppsAdmin : null,
    errorHandlingFetcher
  );
  const descriptors = useSWR<BuiltInExternalAppDescriptor[], Error>(
    canLoadApps ? SWR_KEYS.buildExternalAppsBuiltInOptions : null,
    errorHandlingFetcher
  );
  const hasError = Boolean(apps.error || descriptors.error);
  const availableApps =
    !hasError && descriptors.data && apps.data
      ? availableBuiltInDescriptors(descriptors.data, apps.data)
      : [];
  return (
    <Modal open onOpenChange={(open) => !open && onClose()}>
      <Modal.Content width="lg" position="top" preventAccidentalClose={false}>
        <Modal.Header title={t(`kind.${catalogKind}`)} onClose={onClose} />
        <Modal.Body alignItems="stretch">
          <div className="flex w-full flex-col gap-4">
            {catalogKind === "mcp" && canManageActions && (
              <section
                aria-label={t("kind.mcp")}
                className="flex flex-col gap-1"
              >
                <div className="grid grid-cols-1 gap-x-4 gap-y-1 md:grid-cols-2">
                  {SUGGESTED_MCP_PLUGINS.filter(
                    (plugin) =>
                      !installedEndpoints.has(
                        plugin.serverUrl.replace(/\/+$/, "")
                      )
                  ).map((plugin) => (
                    <PluginCatalogCard
                      key={plugin.id}
                      icon={plugin.icon}
                      title={plugin.name}
                      description={t(`catalog.${plugin.id}.summary`)}
                      label={t("catalog.add.label", { name: plugin.name })}
                      onSelect={() =>
                        onPick({ kind: "mcp", suggestion: plugin })
                      }
                    />
                  ))}
                  <PluginCatalogCard
                    icon={SvgServer}
                    title={t("add.mcp")}
                    description=""
                    label={t("add.mcp")}
                    onSelect={() => onPick({ kind: "mcp" })}
                  />
                </div>
              </section>
            )}
            {catalogKind === "external-app" && isGlobalHolder && (
              <>
                <section
                  aria-label={t("kind.external-app")}
                  className="flex flex-col gap-1"
                >
                  {hasError && (
                    <div className="flex items-center justify-between gap-4">
                      <Text font="secondary-body" color="text-03">
                        {t("state.externalAppsError")}
                      </Text>
                      <Button
                        prominence="secondary"
                        onClick={() => {
                          void apps.mutate();
                          void descriptors.mutate();
                        }}
                      >
                        {t("state.retry.label")}
                      </Button>
                    </div>
                  )}
                  {(!descriptors.data || !apps.data) && !hasError && (
                    <LineLoader lines={2} />
                  )}
                  <div className="grid grid-cols-1 gap-x-4 gap-y-1 md:grid-cols-2">
                    {availableApps.map((descriptor) => (
                      <PluginCatalogCard
                        icon={getAppTypeLogo(descriptor.app_type)}
                        title={descriptor.name}
                        description={t("availability.craft")}
                        label={t("catalog.add.label", {
                          name: descriptor.name,
                        })}
                        key={descriptor.app_type}
                        onSelect={() =>
                          onPick({ kind: "external-app", descriptor })
                        }
                      />
                    ))}
                    <PluginCatalogCard
                      icon={SvgPlug}
                      title={tApps("customApp.title")}
                      description={tApps("customApp.description")}
                      label={tApps("customApp.title")}
                      onSelect={() => onPick({ kind: "external-app" })}
                    />
                  </div>
                </section>
              </>
            )}
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
