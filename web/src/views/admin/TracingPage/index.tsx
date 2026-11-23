"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { SettingsLayouts, toast } from "@opal/layouts";
import ProviderCard from "@/sections/admin/ProviderCard";
import { FetchError } from "@/lib/fetcher";
import { useCreateModal } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useTracingProviders } from "@/lib/tracing/hooks";
import {
  TRACING_PROVIDER_DETAILS,
  TRACING_PROVIDER_ORDER,
} from "@/lib/tracing/utils";
import type {
  TracingDisconnectTarget,
  TracingProviderType,
  TracingProviderView,
} from "@/lib/tracing/types";
import {
  deleteTracingProvider,
  reconnectTracingProvider,
} from "@/lib/tracing/svc";
import {
  TracingSetupModal,
  type TracingSetupModalState,
} from "@/views/admin/TracingPage/TracingSetupModal";
import { TracingDisconnectModal } from "@/views/admin/TracingPage/TracingDisconnectModal";
import { TracingDeleteModal } from "@/views/admin/TracingPage/TracingDeleteModal";

const route = ADMIN_ROUTES.TRACING;

interface ShellProps {
  children: ReactNode;
  loading?: boolean;
  /** The page failed to load; the string is its description. */
  error?: string | false;
}

function Shell({ children, loading, error }: ShellProps) {
  const t = useTranslations("admin.tracing");
  const adminRouteTitle = useAdminRouteTitle();

  return (
    <SettingsLayouts.Root loading={loading} error={error}>
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        description={t("page.description")}
        divider
      />
      <SettingsLayouts.Body>{children}</SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default function TracingPage() {
  const t = useTranslations("admin.tracing");
  const [activeProvider, setActiveProvider] =
    useState<TracingSetupModalState | null>(null);
  const [disconnectTarget, setDisconnectTarget] =
    useState<TracingDisconnectTarget | null>(null);
  const setupModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const [deleteTarget, setDeleteTarget] =
    useState<TracingDisconnectTarget | null>(null);
  const deleteModal = useCreateModal();
  const { providers, error, isLoading, mutateProviders } =
    useTracingProviders();

  // The server's detail when it gives one, else the generic description.
  const loadError: string | false = error
    ? (error instanceof FetchError && typeof error.info?.detail === "string"
        ? error.info.detail
        : error.message) || t("loadError.description")
    : false;

  function openSetup(
    providerType: TracingProviderType,
    provider: TracingProviderView | null
  ) {
    setActiveProvider({
      providerType,
      detail: TRACING_PROVIDER_DETAILS[providerType],
      provider,
    });
    setupModal.toggle(true);
  }

  async function handleReconnect(
    target: TracingDisconnectTarget,
    provider: TracingProviderView | null
  ) {
    try {
      if (provider?.masked_api_key) {
        await reconnectTracingProvider(target.providerType, target.config);
      } else if (provider?.env_configured) {
        // The row only switches off an env-var config; removing it turns
        // that config back on.
        await deleteTracingProvider(target.providerType);
      } else {
        // Saved settings without a key: the admin enters one in setup.
        openSetup(target.providerType, provider);
        return;
      }
    } catch (reconnectError) {
      toast.error(
        reconnectError instanceof Error && reconnectError.message
          ? reconnectError.message
          : t("toasts.unexpectedError")
      );
    } finally {
      await Promise.allSettled([mutateProviders()]);
    }
  }

  return (
    <>
      <Shell loading={isLoading} error={loadError}>
        <div className="flex w-full flex-col gap-2">
          {TRACING_PROVIDER_ORDER.map((providerType) => {
            const detail = TRACING_PROVIDER_DETAILS[providerType];
            const provider =
              providers.find((p) => p.provider_type === providerType) ?? null;
            const connected = provider?.connected ?? false;
            // Saved settings that are switched off: it can be reconnected.
            const disconnected = !connected && provider?.source === "db";
            const target: TracingDisconnectTarget = {
              providerType,
              label: detail.label,
              config: provider?.config ?? {},
            };
            // Connect and configure open the same setup modal.
            const openCardSetup = () => openSetup(providerType, provider);

            return (
              <ProviderCard
                key={providerType}
                icon={detail.logo}
                title={detail.label}
                titleSuffix={
                  disconnected ? t("provider.disconnected.suffix") : undefined
                }
                description={t(detail.descriptionKey)}
                status={connected ? "connected" : "disconnected"}
                connectedLabel={t("provider.connected.label")}
                onConnect={openCardSetup}
                onReconnect={
                  disconnected
                    ? () => void handleReconnect(target, provider)
                    : undefined
                }
                onEdit={connected || disconnected ? openCardSetup : undefined}
                onDisconnect={
                  connected
                    ? () => {
                        setDisconnectTarget(target);
                        disconnectModal.toggle(true);
                      }
                    : undefined
                }
                // Only saved credentials can be deleted. A row with no key just
                // switched off an env-var config.
                onDelete={
                  disconnected && provider?.masked_api_key
                    ? () => {
                        setDeleteTarget(target);
                        deleteModal.toggle(true);
                      }
                    : undefined
                }
                disconnectModalOpen={
                  (disconnectModal.isOpen &&
                    disconnectTarget?.providerType === providerType) ||
                  (deleteModal.isOpen &&
                    deleteTarget?.providerType === providerType)
                }
                setupModalOpen={
                  setupModal.isOpen &&
                  activeProvider?.providerType === providerType
                }
              />
            );
          })}
        </div>
      </Shell>

      {activeProvider && (
        <setupModal.Provider>
          <TracingSetupModal
            state={activeProvider}
            onSaved={async () => {
              await mutateProviders();
            }}
          />
        </setupModal.Provider>
      )}

      {deleteTarget && (
        <deleteModal.Provider>
          <TracingDeleteModal
            target={deleteTarget}
            envConfigured={
              providers.find(
                (p) => p.provider_type === deleteTarget.providerType
              )?.env_configured ?? false
            }
            onDeleted={async () => {
              await mutateProviders();
            }}
          />
        </deleteModal.Provider>
      )}

      {disconnectTarget && (
        <disconnectModal.Provider>
          <TracingDisconnectModal
            target={disconnectTarget}
            onDisconnected={async () => {
              await mutateProviders();
            }}
          />
        </disconnectModal.Provider>
      )}
    </>
  );
}
