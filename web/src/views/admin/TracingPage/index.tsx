"use client";

import { useState, type ReactNode } from "react";
import { SettingsLayouts } from "@opal/layouts";
import { MessageCard } from "@opal/components";
import ProviderCard from "@/sections/admin/ProviderCard";
import { FetchError } from "@/lib/fetcher";
import { PageLoader } from "@/refresh-components/PageLoader";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useTracingProviders } from "@/lib/tracing/hooks";
import { TRACING_PROVIDERS } from "@/lib/tracing/constants";
import type { TracingProviderView } from "@/lib/tracing/types";
import {
  TracingSetupModal,
  type TracingSetupModalState,
} from "@/views/admin/TracingPage/TracingSetupModal";
import { TracingDisconnectModal } from "@/views/admin/TracingPage/TracingDisconnectModal";

const route = ADMIN_ROUTES.TRACING;
const DESCRIPTION =
  "Connect observability platforms to monitor and evaluate LLM calls.";

function Shell({ children }: { children: ReactNode }) {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={DESCRIPTION}
        divider
      />
      <SettingsLayouts.Body>{children}</SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default function TracingPage() {
  const [activeProvider, setActiveProvider] =
    useState<TracingSetupModalState | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<{
    providerType: TracingProviderView["provider_type"];
    label: string;
  } | null>(null);
  const setupModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const { providers, error, isLoading, mutateProviders } =
    useTracingProviders();

  if (error) {
    const detail =
      error instanceof FetchError && typeof error.info?.detail === "string"
        ? error.info.detail
        : error.message;
    return (
      <Shell>
        <MessageCard
          variant="error"
          title="Failed to load tracing settings"
          description={detail ?? "Unable to load tracing configuration."}
        />
      </Shell>
    );
  }

  if (isLoading) {
    return (
      <Shell>
        <PageLoader />
      </Shell>
    );
  }

  return (
    <>
      <Shell>
        <div className="flex w-full flex-col gap-2">
          {TRACING_PROVIDERS.map((meta) => {
            const provider =
              providers.find((p) => p.provider_type === meta.type) ?? null;
            const connected = provider?.connected ?? false;
            // Only DB-backed providers can be disconnected (env config lives
            // outside the UI).
            const canDisconnect = provider?.source === "db";

            return (
              <ProviderCard
                key={meta.type}
                icon={route.icon}
                title={meta.label}
                description={meta.description}
                status={connected ? "selected" : "disconnected"}
                selectedLabel="Connected"
                onConnect={() => {
                  setActiveProvider({ meta, provider });
                  setupModal.toggle(true);
                }}
                onEdit={
                  connected
                    ? () => {
                        setActiveProvider({ meta, provider });
                        setupModal.toggle(true);
                      }
                    : undefined
                }
                onDisconnect={
                  connected && canDisconnect
                    ? () => {
                        setDisconnectTarget({
                          providerType: meta.type,
                          label: meta.label,
                        });
                        disconnectModal.toggle(true);
                      }
                    : undefined
                }
                disconnectModalOpen={
                  disconnectModal.isOpen &&
                  disconnectTarget?.providerType === meta.type
                }
                setupModalOpen={
                  setupModal.isOpen && activeProvider?.meta.type === meta.type
                }
              />
            );
          })}
        </div>
      </Shell>

      {activeProvider && (
        <setupModal.Provider>
          <TracingSetupModal state={activeProvider} onSaved={mutateProviders} />
        </setupModal.Provider>
      )}

      {disconnectTarget && (
        <disconnectModal.Provider>
          <TracingDisconnectModal
            target={disconnectTarget}
            onDisconnected={mutateProviders}
          />
        </disconnectModal.Provider>
      )}
    </>
  );
}
