"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Card, MessageCard, Switch } from "@opal/components";
import { SvgCopy, SvgPlus, SvgSettings } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  ContentAction,
  IllustrationContent,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { cn } from "@opal/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/settings/types";
import type { SSOProviderResponse } from "@/lib/sso/interfaces";
import { tierAtLeast } from "@/lib/tiers";
import { setSSOProviderEnabled } from "@/lib/sso/svc";
import { copyRedirectUri, SSO_PROVIDER_DETAILS } from "@/lib/sso/utils";
import { SWR_KEYS } from "@/lib/swr-keys";
import { PageLoader } from "@/refresh-components/PageLoader";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { SSOProviderModal } from "@/sections/modals/sso/SSOProviderModal";

const route = ADMIN_ROUTES.SSO_PROVIDERS;
const DESCRIPTION = "Let users sign in through your identity provider.";

interface ShellProps {
  children: React.ReactNode;
  onAddProvider: () => void;
  addGated?: boolean;
}

function Shell({ children, onAddProvider, addGated }: ShellProps) {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={DESCRIPTION}
        divider
        rightChildren={
          <Button
            icon={SvgPlus}
            onClick={onAddProvider}
            disabled={addGated}
            tooltip={
              addGated
                ? "Multiple enabled SSO providers are available on the Business or Enterprise plan."
                : undefined
            }
          >
            Add Provider
          </Button>
        }
      />
      <SettingsLayouts.Body>{children}</SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default function SSOProvidersPage() {
  const [editProvider, setEditProvider] = useState<SSOProviderResponse | null>(
    null
  );
  const [pendingProviderId, setPendingProviderId] = useState<number | null>(
    null
  );
  const setupModal = useCreateModal();
  const settings = useSettings();
  const {
    data: providers,
    error,
    isLoading,
    mutate,
  } = useSWR<SSOProviderResponse[]>(
    SWR_KEYS.adminSsoProviders,
    errorHandlingFetcher
  );

  // Mirrors the backend gate: below Business, adding is blocked only while
  // another provider is enabled (new providers are created enabled).
  const addGated =
    !tierAtLeast(settings?.tier, Tier.BUSINESS) &&
    Boolean(providers?.some((provider) => provider.enabled));

  function openCreateModal() {
    setEditProvider(null);
    setupModal.toggle(true);
  }

  function openEditModal(provider: SSOProviderResponse) {
    setEditProvider(provider);
    setupModal.toggle(true);
  }

  async function handleEnabledChange(
    provider: SSOProviderResponse,
    enabled: boolean
  ): Promise<void> {
    setPendingProviderId(provider.id);

    try {
      await setSSOProviderEnabled(provider.id, enabled);
      await mutate();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Unexpected error occurred."
      );
    } finally {
      setPendingProviderId(null);
    }
  }

  if (error) {
    const detail =
      error instanceof FetchError && typeof error.info?.detail === "string"
        ? error.info.detail
        : error.message;

    return (
      <Shell onAddProvider={openCreateModal} addGated={addGated}>
        <MessageCard
          variant="error"
          title="Failed to load SSO providers"
          description={detail ?? "Unable to load SSO providers."}
        />
      </Shell>
    );
  }

  if (isLoading) {
    return (
      <Shell onAddProvider={openCreateModal} addGated={addGated}>
        <PageLoader />
      </Shell>
    );
  }

  return (
    <>
      <Shell onAddProvider={openCreateModal} addGated={addGated}>
        {!providers?.length ? (
          <IllustrationContent
            illustration={SvgNoResult}
            title="No SSO providers yet"
            description="Add a provider to let users sign in with Google, OIDC, or SAML."
          />
        ) : (
          <div className={cn("flex w-full flex-col gap-2")}>
            {providers.map((provider) => {
              const isPending = pendingProviderId === provider.id;

              return (
                <Card key={provider.id} border="solid" rounding="lg">
                  <ContentAction
                    icon={SSO_PROVIDER_DETAILS[provider.provider_type].icon}
                    title={provider.display_name}
                    suffix={SSO_PROVIDER_DETAILS[provider.provider_type].label}
                    description={provider.redirect_uri}
                    sizePreset="main-ui"
                    variant="section"
                    padding="md"
                    rightChildren={
                      <div
                        className={cn(
                          "flex h-full items-center gap-2 self-center"
                        )}
                      >
                        <Button
                          icon={SvgCopy}
                          prominence="tertiary"
                          size="sm"
                          tooltip="Copy redirect URI"
                          disabled={isPending}
                          onClick={() => {
                            void copyRedirectUri(provider.redirect_uri);
                          }}
                        />
                        <Switch
                          checked={provider.enabled}
                          disabled={isPending}
                          onCheckedChange={(enabled) => {
                            void handleEnabledChange(provider, enabled);
                          }}
                        />
                        <Button
                          icon={SvgSettings}
                          prominence="tertiary"
                          size="sm"
                          tooltip="Edit"
                          disabled={isPending}
                          onClick={() => {
                            openEditModal(provider);
                          }}
                        />
                      </div>
                    }
                  />
                </Card>
              );
            })}
          </div>
        )}
      </Shell>

      <setupModal.Provider>
        <SSOProviderModal provider={editProvider} onSaved={() => mutate()} />
      </setupModal.Provider>
    </>
  );
}
