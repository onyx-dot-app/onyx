"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Section, SettingsLayouts, toast } from "@opal/layouts";
import { IntegrationCard } from "@/sections/admin/IntegrationCard";
import { IntegrationConfirmModal } from "@/sections/admin/IntegrationConfirmModal";
import { FetchError } from "@/lib/fetcher";
import { Text, useCreateModal } from "@opal/components";
import { SvgTrash, SvgUnplug } from "@opal/icons";
import { markdown } from "@opal/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useTracingProviders } from "@/lib/tracing/hooks";
import {
  TRACING_PROVIDER_DETAILS,
  TRACING_PROVIDER_ORDER,
} from "@/lib/tracing/utils";
import type {
  TracingDisconnectTarget,
  TracingProviderView,
} from "@/lib/tracing/types";
import {
  deleteTracingProvider,
  disconnectTracingProvider,
  reconnectTracingProvider,
} from "@/lib/tracing/svc";
import {
  TracingSetupModal,
  type TracingSetupModalState,
} from "@/views/admin/TracingPage/TracingSetupModal";

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

  async function handleReconnect(
    target: TracingDisconnectTarget,
    provider: TracingProviderView | null
  ) {
    try {
      // A row with no saved key only switched off an env-var config; removing
      // it turns that config back on.
      if (provider?.masked_api_key) {
        await reconnectTracingProvider(target.providerType, target.config);
      } else {
        await deleteTracingProvider(target.providerType);
      }
    } catch (reconnectError) {
      toast.error(
        reconnectError instanceof Error
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
            const openSetup = () => {
              setActiveProvider({ providerType, detail, provider });
              setupModal.toggle(true);
            };

            return (
              <IntegrationCard
                key={providerType}
                icon={detail.logo}
                title={detail.label}
                description={t(detail.descriptionKey)}
                state={
                  connected
                    ? "connected"
                    : disconnected
                      ? "disconnected"
                      : "not_set_up"
                }
                onConnect={openSetup}
                onConfigure={openSetup}
                onDisconnect={() => {
                  setDisconnectTarget(target);
                  disconnectModal.toggle(true);
                }}
                onReconnect={() => void handleReconnect(target, provider)}
                // Only saved credentials can be deleted. A row with no key just
                // switched off an env-var config.
                onDelete={
                  provider?.masked_api_key
                    ? () => {
                        setDeleteTarget(target);
                        deleteModal.toggle(true);
                      }
                    : undefined
                }
                holdHover={
                  (disconnectModal.isOpen &&
                    disconnectTarget?.providerType === providerType) ||
                  (deleteModal.isOpen &&
                    deleteTarget?.providerType === providerType) ||
                  (setupModal.isOpen &&
                    activeProvider?.providerType === providerType)
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
          <IntegrationConfirmModal
            icon={SvgTrash}
            title={t("deleteModal.title", { label: deleteTarget.label })}
            description={t("deleteModal.description")}
            submitLabel={t("deleteModal.submit.label")}
            errorMessage={t("toasts.unexpectedError")}
            onConfirm={() => deleteTracingProvider(deleteTarget.providerType)}
            onSettled={async () => {
              await mutateProviders();
            }}
          >
            <Section alignItems="start" gap={2}>
              <Text color="text-03">
                {markdown(t("deleteModal.body", { label: deleteTarget.label }))}
              </Text>
            </Section>
          </IntegrationConfirmModal>
        </deleteModal.Provider>
      )}

      {disconnectTarget && (
        <disconnectModal.Provider>
          <IntegrationConfirmModal
            icon={SvgUnplug}
            title={t("disconnectModal.title", {
              label: disconnectTarget.label,
            })}
            description={t("disconnectModal.description")}
            submitLabel={t("disconnectModal.submit.label")}
            errorMessage={t("toasts.unexpectedError")}
            onConfirm={() =>
              disconnectTracingProvider(
                disconnectTarget.providerType,
                disconnectTarget.config
              )
            }
            onSettled={async () => {
              await mutateProviders();
            }}
          >
            <Section alignItems="start" gap={2}>
              <Text color="text-03">
                {markdown(
                  t("disconnectModal.body", { label: disconnectTarget.label })
                )}
              </Text>
            </Section>
          </IntegrationConfirmModal>
        </disconnectModal.Provider>
      )}
    </>
  );
}
