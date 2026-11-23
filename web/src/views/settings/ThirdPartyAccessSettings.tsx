"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { useNavigation } from "@opal/navigation";
import {
  ConfirmationModalLayout,
  Content,
  ContentAction,
  Section,
  toast,
} from "@opal/layouts";
import {
  AttachmentItemButton,
  Button,
  Card,
  InputTypeIn,
  Text,
  useCreateModal,
} from "@opal/components";
import {
  SvgArrowExchange,
  SvgKey,
  SvgPlusCircle,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { Permission, type FederatedConnectorOAuthStatus } from "@/lib/types";
import { Tier } from "@/lib/tiers/types";
import { tierAtLeast } from "@/lib/tiers/utils";
import { hasPermission } from "@/lib/permissions/utils";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";
import useFilter from "@/hooks/useFilter";
import { useCloudSubscription } from "@/hooks/useCloudSubscription";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import OAuthProviderConnections from "@/sections/oauth-provider/OAuthProviderConnections";
import { PATModal, usePATCreation } from "@/views/settings/PATModal";
import LLMGatewaySection from "@/views/settings/LLMGatewaySection";
import SettingsSection from "@/views/settings/SettingsSection";
import type { PAT, PatScopeOption } from "@/views/settings/types";

function PersonalAccessTokensSection() {
  const t = useTranslations("settings");
  const navigation = useNavigation();
  const { permissions } = useUser();
  const [tokenToDelete, setTokenToDelete] = useState<PAT | null>(null);
  const revokeModal = useCreateModal();

  const canCreateTokens = useCloudSubscription();
  const canCreatePAT = hasPermission(
    permissions,
    Permission.CREATE_USER_API_KEYS
  );

  const {
    data: pats = [],
    mutate,
    error,
    isLoading,
  } = useSWR<PAT[]>(SWR_KEYS.userPats, errorHandlingFetcher, {
    revalidateOnFocus: true,
    dedupingInterval: 2000,
    fallbackData: [],
  });

  // Hide the section when the user cannot create tokens and owns none.
  const showTokensSection = isLoading || canCreatePAT || pats.length > 0;

  const { data: allScopeOptions = [], error: scopeOptionsError } = useSWR<
    PatScopeOption[]
  >(
    showTokensSection && canCreateTokens ? SWR_KEYS.userPatScopes : null,
    errorHandlingFetcher,
    { fallbackData: [] }
  );
  const { tier: currentTier, appName } = useSettings();
  const scopeOptions = useMemo(
    () =>
      // Undefined tier (settings loading/failed) must not hide Community scopes.
      allScopeOptions.filter((option) =>
        tierAtLeast(currentTier ?? Tier.COMMUNITY, option.min_tier)
      ),
    [allScopeOptions, currentTier]
  );
  const tokenCreation = usePATCreation();

  const scopeLabels = useMemo(
    () =>
      new Map(
        scopeOptions.map((o) => [
          o.scope,
          `${o.label} ${o.group_label.toLowerCase()}`,
        ])
      ),
    [scopeOptions]
  );

  // Use filter hook for searching tokens
  const {
    query,
    setQuery,
    filtered: filteredPats,
  } = useFilter(pats, (pat) => `${pat.name} ${pat.token_display}`);

  // Show error popup if SWR fetch fails
  useEffect(() => {
    if (error) {
      toast.error(t("apiKeys.toasts.loadFailed"));
    }
  }, [error, t]);

  useEffect(() => {
    if (scopeOptionsError) {
      toast.error(t("apiKeys.toasts.loadPermissionsFailed"));
    }
  }, [scopeOptionsError, t]);

  const deletePAT = useCallback(
    async (patId: number) => {
      try {
        const response = await fetch(`/api/user/pats/${patId}`, {
          method: "DELETE",
        });

        if (response.ok) {
          // Clear the newly created token if it's the one being deleted
          if (tokenCreation.newlyCreatedToken?.id === patId) {
            tokenCreation.closeTokenModal();
          }
          await mutate();
          revokeModal.toggle(false);
        } else {
          toast.error(t("apiKeys.toasts.deleteFailed"));
        }
      } catch (error) {
        toast.error(t("apiKeys.toasts.deleteNetworkError"));
      }
    },
    [mutate, revokeModal.toggle, tokenCreation, t]
  );

  if (!showTokensSection) {
    return null;
  }

  return (
    <>
      <tokenCreation.CreateModalProvider>
        <PATModal
          isCreating={tokenCreation.isCreating}
          newTokenName={tokenCreation.newTokenName}
          setNewTokenName={tokenCreation.setNewTokenName}
          expirationDays={tokenCreation.expirationDays}
          setExpirationDays={tokenCreation.setExpirationDays}
          accessMode={tokenCreation.accessMode}
          setAccessMode={tokenCreation.setAccessMode}
          defaultAccessMode={tokenCreation.defaultAccessMode}
          scopeOptions={scopeOptions}
          scopesError={Boolean(scopeOptionsError)}
          selectedScopes={tokenCreation.selectedScopes}
          toggleScope={tokenCreation.toggleScope}
          onClose={tokenCreation.closeTokenModal}
          onCreate={tokenCreation.createPAT}
          createdToken={tokenCreation.newlyCreatedToken}
        />
      </tokenCreation.CreateModalProvider>

      <revokeModal.Provider>
        {tokenToDelete && (
          <ConfirmationModalLayout
            icon={SvgTrash}
            title={t("apiKeys.revokeModal.title")}
            onClose={() => revokeModal.toggle(false)}
            submit={
              <Button
                variant="danger"
                onClick={() => deletePAT(tokenToDelete.id)}
              >
                {t("apiKeys.revokeModal.submit")}
              </Button>
            }
          >
            <Section gap={2} alignItems="start">
              <Text as="p" font="main-ui-body" color="text-05">
                {t("apiKeys.revokeModal.description", {
                  name: tokenToDelete.name,
                  tokenDisplay: tokenToDelete.token_display,
                  appName,
                })}
              </Text>
              <Text as="p" font="main-ui-body" color="text-05">
                {t("apiKeys.revokeModal.question")}
              </Text>
            </Section>
          </ConfirmationModalLayout>
        )}
      </revokeModal.Provider>

      <Section gap={3}>
        <Content
          font="main-content-emphasis"
          title={t("apiKeys.section.title")}
          width="full"
        />
        {canCreateTokens ? (
          <Card border="solid" padding={1} rounding={4}>
            <Section alignItems="start" height="fit">
              <Section gap={0}>
                <Section flexDirection="row" padding={1} gap={2}>
                  {pats.length === 0 ? (
                    <Section
                      padding={2}
                      alignItems="start"
                      data-testid="access-token-list-status"
                    >
                      <Text as="p" font="secondary-body" color="text-03">
                        {isLoading
                          ? t("apiKeys.list.loading")
                          : t("apiKeys.list.empty")}
                      </Text>
                    </Section>
                  ) : (
                    <InputTypeIn
                      placeholder={t("apiKeys.list.searchPlaceholder")}
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      icon="search"
                      variant="internal"
                    />
                  )}
                  <div className="shrink-0">
                    <Button
                      rightIcon={SvgPlusCircle}
                      prominence="internal"
                      interaction={
                        tokenCreation.showCreateModal ? "active" : "rest"
                      }
                      onClick={tokenCreation.openTokenModal}
                      disabled={!canCreatePAT}
                      tooltip={
                        !canCreatePAT
                          ? t("apiKeys.list.noPermissionTooltip")
                          : undefined
                      }
                    >
                      {t("apiKeys.list.newTokenButton")}
                    </Button>
                  </div>
                </Section>

                <Section gap={1}>
                  {filteredPats.map((pat) => {
                    const now = new Date();
                    const createdDate = new Date(pat.created_at);
                    const daysSinceCreation = Math.floor(
                      (now.getTime() - createdDate.getTime()) /
                        (1000 * 60 * 60 * 24)
                    );

                    let expiryText = t("apiKeys.list.neverExpires");
                    if (pat.expires_at) {
                      const expiresDate = new Date(pat.expires_at);
                      const daysUntilExpiry = Math.ceil(
                        (expiresDate.getTime() - now.getTime()) /
                          (1000 * 60 * 60 * 24)
                      );
                      expiryText = t("apiKeys.list.expiresIn", {
                        count: daysUntilExpiry,
                      });
                    }

                    const scopeText =
                      pat.scopes === null
                        ? t("apiKeys.createModal.permissions.fullAccessOption")
                        : pat.scopes
                            .map((scope) => scopeLabels.get(scope) ?? scope)
                            .join(", ");

                    const createdText =
                      daysSinceCreation === 0
                        ? t("apiKeys.list.createdToday")
                        : t("apiKeys.list.createdDaysAgo", {
                            count: daysSinceCreation,
                          });

                    const middleText = t("apiKeys.list.middleText", {
                      created: createdText,
                      expiry: expiryText,
                      scope: scopeText,
                    });

                    return (
                      <AttachmentItemButton
                        key={pat.id}
                        presentational
                        prominence="secondary"
                        icon={SvgKey}
                        title={pat.name}
                        description={pat.token_display}
                        centerChildren={
                          <Section alignItems="end">
                            <Text
                              as="p"
                              font="secondary-body"
                              color="text-03"
                              maxLines={1}
                            >
                              {middleText}
                            </Text>
                          </Section>
                        }
                        rightChildren={
                          <Button
                            icon={SvgTrash}
                            onClick={() => {
                              setTokenToDelete(pat);
                              revokeModal.toggle(true);
                            }}
                            prominence="tertiary"
                            size="sm"
                            aria-label={t("apiKeys.list.deleteTokenAriaLabel", {
                              name: pat.name,
                            })}
                          />
                        }
                      />
                    );
                  })}
                </Section>
              </Section>
            </Section>
          </Card>
        ) : (
          <Card border="solid" rounding={4}>
            <Section alignItems="start" height="fit">
              <Section flexDirection="row" justifyContent="between">
                <Text as="p" font="secondary-body" color="text-03">
                  {t("apiKeys.upsell.description")}
                </Text>
                <Button
                  prominence="secondary"
                  {...navigation.linkTo("/admin/billing")}
                >
                  {t("apiKeys.upsell.upgradeButton")}
                </Button>
              </Section>
            </Section>
          </Card>
        )}
      </Section>
    </>
  );
}

interface FederatedConnectorRowProps {
  connector: FederatedConnectorOAuthStatus;
  onDisconnectSuccess: () => void;
}

function FederatedConnectorRow({
  connector,
  onDisconnectSuccess,
}: FederatedConnectorRowProps) {
  const t = useTranslations("settings");
  const { appName } = useSettings();
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const disconnectModal = useCreateModal();
  // SAFETY: federated connector sources are ValidSources values.
  const sourceMetadata = getSourceMetadata(connector.source as ValidSources);

  const handleDisconnect = useCallback(async () => {
    setIsDisconnecting(true);
    try {
      const response = await fetch(
        `/api/federated/${connector.federated_connector_id}/oauth`,
        { method: "DELETE" }
      );

      if (response.ok) {
        disconnectModal.toggle(false);
        onDisconnectSuccess();
      } else {
        throw new Error("Failed to disconnect");
      }
    } catch (error) {
      toast.error(t("connectors.toasts.disconnectFailed"));
    } finally {
      setIsDisconnecting(false);
    }
  }, [
    connector.federated_connector_id,
    disconnectModal.toggle,
    onDisconnectSuccess,
    t,
  ]);

  return (
    <>
      <disconnectModal.Provider>
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={markdown(
            t("connectors.disconnectModal.title", {
              name: sourceMetadata.displayName,
            })
          )}
          onClose={() => disconnectModal.toggle(false)}
          submit={
            <Button
              disabled={isDisconnecting}
              variant="danger"
              onClick={() => void handleDisconnect()}
            >
              {isDisconnecting
                ? t("connectors.disconnectModal.disconnecting")
                : t("connectors.disconnectModal.submit")}
            </Button>
          }
        >
          <Section gap={2} alignItems="start">
            <Text as="p" font="main-ui-body" color="text-05">
              {t("connectors.disconnectModal.description", {
                name: sourceMetadata.displayName,
                appName,
              })}
            </Text>
            <Text as="p" font="main-ui-body" color="text-05">
              {t("connectors.disconnectModal.continueNote", {
                name: sourceMetadata.displayName,
              })}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      </disconnectModal.Provider>

      <ContentAction
        font="main-ui-action"
        icon={sourceMetadata.icon}
        title={sourceMetadata.displayName}
        description={
          connector.has_oauth_token
            ? t("connectors.status.connected")
            : t("connectors.status.notConnected")
        }
        width="full"
        padding={0}
        center
        rightChildren={
          connector.has_oauth_token ? (
            <Button
              disabled={isDisconnecting}
              icon={SvgUnplug}
              prominence="tertiary"
              size="sm"
              aria-label={t("connectors.disconnectAriaLabel", {
                name: sourceMetadata.displayName,
              })}
              onClick={() => disconnectModal.toggle(true)}
            />
          ) : connector.authorize_url ? (
            <Button
              prominence="internal"
              href={connector.authorize_url}
              target="_blank"
              rightIcon={SvgArrowExchange}
            >
              {t("connectors.connectButton")}
            </Button>
          ) : undefined
        }
      />
    </>
  );
}

export default function ThirdPartyAccessSettings() {
  const t = useTranslations("settings");
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();

  return (
    <Section gap={8}>
      <PersonalAccessTokensSection />
      <OAuthProviderConnections />
      {federatedConnectors.length > 0 && (
        <SettingsSection title={t("connectors.title")}>
          {federatedConnectors.map((connector) => (
            <FederatedConnectorRow
              key={connector.federated_connector_id}
              connector={connector}
              onDisconnectSuccess={() => void refetchFederatedConnectors()}
            />
          ))}
        </SettingsSection>
      )}
      <LLMGatewaySection />
    </Section>
  );
}
