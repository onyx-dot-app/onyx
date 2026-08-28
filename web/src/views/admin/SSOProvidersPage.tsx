"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
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
import { PageLoader } from "@opal/layouts";
import { useCreateModal } from "@opal/components";
import { SSOProviderModal } from "@/sections/modals/sso/SSOProviderModal";

const route = ADMIN_ROUTES.SSO_PROVIDERS;

interface ShellProps {
  children: React.ReactNode;
  onAddProvider: () => void;
  addGated?: boolean;
}

function Shell({ children, onAddProvider, addGated }: ShellProps) {
  const t = useTranslations("admin.ssoProviders");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={t("page.description")}
        divider
        rightChildren={
          <Button
            icon={SvgPlus}
            onClick={onAddProvider}
            disabled={addGated}
            tooltip={addGated ? t("addProvider.gatedTooltip") : undefined}
          >
            {t("addProvider.button.label")}
          </Button>
        }
      />
      <SettingsLayouts.Body>{children}</SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default function SSOProvidersPage() {
  const t = useTranslations("admin.ssoProviders");
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
        error instanceof Error ? error.message : t("toasts.unexpectedError")
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
          title={t("loadError.title")}
          description={detail ?? t("loadError.description")}
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
            title={t("empty.title")}
            description={t("empty.description")}
          />
        ) : (
          <div className={cn("flex w-full flex-col gap-2")}>
            {providers.map((provider) => {
              const isPending = pendingProviderId === provider.id;

              return (
                <Card key={provider.id} border="solid" rounding={4}>
                  <ContentAction
                    icon={SSO_PROVIDER_DETAILS[provider.provider_type].icon}
                    title={provider.display_name}
                    suffix={SSO_PROVIDER_DETAILS[provider.provider_type].label}
                    description={provider.redirect_uri}
                    sizePreset="main-ui"
                    variant="section"
                    padding={1}
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
                          tooltip={t("copyRedirectUri.tooltip")}
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
                          tooltip={t("editProvider.tooltip")}
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
        <SSOProviderModal
          provider={editProvider}
          onSaved={async () => {
            await mutate();
          }}
        />
      </setupModal.Provider>
    </>
  );
}
