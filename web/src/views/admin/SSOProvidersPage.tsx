"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Card, MessageCard, InputSwitch, Text } from "@opal/components";
import { SvgCopy, SvgPlus, SvgSettings, SvgTrash } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  ConfirmationModalLayout,
  ContentAction,
  IllustrationContent,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { cn } from "@opal/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/tiers/types";
import type {
  SSOProviderHandoffResponse,
  SSOProviderResponse,
} from "@/lib/sso/types";
import { tierAtLeast } from "@/lib/tiers/utils";
import { deleteSSOProvider, setSSOProviderEnabled } from "@/lib/sso/svc";
import { copyRedirectUri, SSO_PROVIDER_DETAILS } from "@/lib/sso/utils";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useCreateModal } from "@opal/components";
import { SSOProviderModal } from "@/sections/modals/sso/SSOProviderModal";

const route = ADMIN_ROUTES.SSO_PROVIDERS;

interface ShellProps {
  children: React.ReactNode;
  onAddProvider: () => void;
  addGated?: boolean;
  loading?: boolean;
}

function Shell({ children, onAddProvider, addGated, loading }: ShellProps) {
  const t = useTranslations("admin.ssoProviders");
  const adminRouteTitle = useAdminRouteTitle();

  return (
    <SettingsLayouts.Root loading={loading}>
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        description={t("page.description")}
        divider
        actions={[
          <Button
            key="primary"
            icon={SvgPlus}
            onClick={onAddProvider}
            disabled={addGated}
            tooltip={addGated ? t("addProvider.gatedTooltip") : undefined}
          >
            {t("addProvider.button.label")}
          </Button>,
        ]}
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
  const [deleteTarget, setDeleteTarget] = useState<SSOProviderResponse | null>(
    null
  );
  const setupModal = useCreateModal();
  const deleteModal = useCreateModal();
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
  // Counts for the delete confirmation, fetched only while a target is picked.
  const {
    data: handoff,
    error: handoffError,
    isLoading: handoffLoading,
  } = useSWR<SSOProviderHandoffResponse>(
    deleteTarget ? SWR_KEYS.adminSsoProviderHandoff(deleteTarget.id) : null,
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

  function openDeleteModal(provider: SSOProviderResponse) {
    setDeleteTarget(provider);
    deleteModal.toggle(true);
  }

  async function handleDelete(provider: SSOProviderResponse): Promise<void> {
    setPendingProviderId(provider.id);

    try {
      await deleteSSOProvider(provider.id);
      await mutate();
      deleteModal.toggle(false);
      toast.success(
        t("toasts.providerDeleted", { name: provider.display_name })
      );
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

  return (
    <>
      <Shell
        onAddProvider={openCreateModal}
        addGated={addGated}
        loading={isLoading}
      >
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
                            void copyRedirectUri(provider.redirect_uri, t);
                          }}
                        />
                        <InputSwitch
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
                        <Button
                          icon={SvgTrash}
                          prominence="tertiary"
                          size="sm"
                          tooltip={t("deleteProvider.tooltip")}
                          disabled={isPending}
                          onClick={() => {
                            openDeleteModal(provider);
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

      {deleteTarget && (
        <deleteModal.Provider>
          <ConfirmationModalLayout
            icon={SvgTrash}
            title={t("modals.deleteProvider.title", {
              name: deleteTarget.display_name,
            })}
            submit={
              <Button
                variant="danger"
                disabled={pendingProviderId === deleteTarget.id || !handoff}
                onClick={() => {
                  void handleDelete(deleteTarget);
                }}
              >
                {t("modals.deleteProvider.submit.label")}
              </Button>
            }
          >
            <Section gap={2} alignItems="start">
              <Text as="p" color="text-03">
                {t("modals.deleteProvider.description", {
                  name: deleteTarget.display_name,
                })}
              </Text>
              {handoffLoading && (
                <Text as="p" color="text-03">
                  {t("modals.deleteProvider.countsLoading")}
                </Text>
              )}
              {handoffError && (
                <Text as="p" color="text-03">
                  {t("modals.deleteProvider.countsError")}
                </Text>
              )}
              {handoff && (
                <Text as="p" color="text-03">
                  {t("modals.deleteProvider.linkedUsers", {
                    count: handoff.linked_users,
                    name: deleteTarget.display_name,
                  })}
                </Text>
              )}
              {handoff && handoff.renamed_users > 0 && (
                <Text as="p" color="text-03">
                  {t("modals.deleteProvider.renamedUsers", {
                    count: handoff.renamed_users,
                  })}
                </Text>
              )}
            </Section>
          </ConfirmationModalLayout>
        </deleteModal.Provider>
      )}
    </>
  );
}
