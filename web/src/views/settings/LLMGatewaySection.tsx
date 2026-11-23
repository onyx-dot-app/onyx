"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import {
  Content,
  IllustrationContent,
  InputHorizontal,
  Section,
  toast,
} from "@opal/layouts";
import { SvgPlugBroken, SvgUnPlugged } from "@opal/illustrations";
import { Button, Collapsible, Text } from "@opal/components";
import { SvgCheck, SvgKey } from "@opal/icons";
import { copyText } from "@opal/utils";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import { LLM_GATEWAY_MIN_TIER, tierAtLeast } from "@/lib/tiers/utils";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";
import { useCloudSubscription } from "@/hooks/useCloudSubscription";
import { hasPermission } from "@/lib/permissions/utils";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { DOCS_BASE_URL } from "@/lib/constants";
import { PATModal, usePATCreation } from "@/views/settings/PATModal";
import SettingsSection from "@/views/settings/SettingsSection";
import type { PatScopeOption } from "@/views/settings/types";

interface GatewayCopyValueButtonProps {
  value: string;
}

function GatewayCopyValueButton({ value }: GatewayCopyValueButtonProps) {
  const t = useTranslations("settings");
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await copyText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("gateway.copyButton.copyError"));
    }
  }

  return (
    <Button
      prominence="secondary"
      size="sm"
      onClick={handleCopy}
      rightIcon={copied ? SvgCheck : undefined}
      tooltip={
        copied ? t("gateway.copyButton.copied") : t("gateway.copyButton.copy")
      }
    >
      {value}
    </Button>
  );
}

function LLMGatewayDetails() {
  const t = useTranslations("settings");
  const { appName, tier: currentTier } = useSettings();
  const { permissions } = useUser();
  const { llmProviders } = useLanguageModels();
  const [gatewayUrl, setGatewayUrl] = useState("");
  // Same gate as the Access Tokens section: this is a second PAT-minting path.
  const canCreatePAT = hasPermission(
    permissions,
    Permission.CREATE_USER_API_KEYS
  );
  const canCreateTokens = useCloudSubscription();
  const tokenCreation = usePATCreation({
    defaultName: t("gateway.title"),
    defaultAccessMode: "limited",
    defaultScopes: ["use:llm_gateway"],
  });
  const { data: allScopeOptions = [], error: scopeOptionsError } = useSWR<
    PatScopeOption[]
  >(canCreateTokens ? SWR_KEYS.userPatScopes : null, errorHandlingFetcher, {
    fallbackData: [],
  });
  const scopeOptions = useMemo(
    () =>
      allScopeOptions.filter((option) =>
        tierAtLeast(currentTier ?? Tier.COMMUNITY, option.min_tier)
      ),
    [allScopeOptions, currentTier]
  );
  const canCreateGatewayToken =
    canCreateTokens &&
    canCreatePAT &&
    scopeOptions.some((option) => option.scope === "use:llm_gateway");

  useEffect(() => {
    setGatewayUrl(`${window.location.origin}/api/gateway/v1`);
  }, []);

  const providerGroups = useMemo(
    () =>
      (llmProviders ?? [])
        .map((provider) => ({
          id: provider.id,
          name: provider.name || provider.provider_display_name,
          models: provider.model_configurations
            .filter((model) => model.is_visible)
            .sort((first, second) => {
              if (
                first.is_recommended_default !== second.is_recommended_default
              ) {
                return first.is_recommended_default ? -1 : 1;
              }

              return first.effectiveDisplayName.localeCompare(
                second.effectiveDisplayName
              );
            })
            .map((model) => ({
              id: `${provider.id}/${model.name}`,
              name: model.effectiveDisplayName,
            })),
        }))
        .filter((provider) => provider.models.length > 0)
        .sort((first, second) => first.name.localeCompare(second.name)),
    [llmProviders]
  );

  const availableModelCount = providerGroups.reduce(
    (count, provider) => count + provider.models.length,
    0
  );

  const gatewayAddress = gatewayUrl || "/api/gateway/v1";

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

      <SettingsSection
        title={t("gateway.title")}
        description={t("gateway.description", { appName })}
        rightChildren={
          <Button
            prominence="tertiary"
            href={`${DOCS_BASE_URL}/developers/guides/llm_gateway`}
            target="_blank"
            size="sm"
          >
            {t("gateway.guideButton")}
          </Button>
        }
      >
        <InputHorizontal
          title={t("gateway.url.title")}
          description={t("gateway.url.description")}
          center
        >
          <GatewayCopyValueButton value={gatewayAddress} />
        </InputHorizontal>

        <Section gap={2} alignItems="start">
          <Content
            font="main-ui-action"
            title={t("gateway.models.title")}
            description={t("gateway.models.description", {
              count: availableModelCount,
            })}
          />

          <Section gap={2} alignItems="start">
            {providerGroups.map((provider) => (
              <Collapsible
                key={provider.id}
                defaultOpen={false}
                title={provider.name}
                description={t("gateway.provider.modelsAvailable", {
                  count: provider.models.length,
                })}
              >
                <Section gap={2} alignItems="start">
                  {provider.models.map((model) => (
                    <Section
                      key={model.id}
                      flexDirection="row"
                      justifyContent="between"
                      alignItems="center"
                      height="fit"
                      gap={2}
                    >
                      <Text as="p" font="main-ui-body" color="text-04">
                        {model.name}
                      </Text>
                      <GatewayCopyValueButton value={model.id} />
                    </Section>
                  ))}
                </Section>
              </Collapsible>
            ))}
          </Section>
        </Section>

        <InputHorizontal
          title={t("gateway.accessToken.title")}
          description={t("gateway.accessToken.description")}
          center
        >
          <Button
            prominence="secondary"
            icon={SvgKey}
            disabled={!canCreateGatewayToken}
            onClick={tokenCreation.openTokenModal}
          >
            {t("gateway.accessToken.button")}
          </Button>
        </InputHorizontal>
      </SettingsSection>
    </>
  );
}

/**
 * The LLM Gateway section of the 3rd Party Access tab. Shows for the gateway tier when
 * the user can see at least one model.
 */
export default function LLMGatewaySection() {
  const t = useTranslations("settings.gateway");
  const gatewayTier = useTierAtLeast(LLM_GATEWAY_MIN_TIER);
  const settings = useSettings();
  const { llmProviders, isLoading, error } = useLanguageModels();

  useEffect(() => {
    if (error) {
      console.error("Failed to load LLM Gateway models", error);
    }
  }, [error]);

  if (!gatewayTier) {
    return null;
  }

  const showModels =
    !error &&
    !settings.isLoading &&
    !isLoading &&
    hasVisibleLLMModel(llmProviders);
  if (showModels && settings.llm_gateway_enabled !== false) {
    return <LLMGatewayDetails />;
  }
  if (!error && !showModels) {
    return null;
  }

  return (
    <SettingsSection title={t("title")}>
      {/* The card aligns rows to the start; center the state. */}
      <Section height="fit">
        <IllustrationContent
          size="sm"
          illustration={error ? SvgPlugBroken : SvgUnPlugged}
          title={error ? t("loadError.title") : t("adminDisabled.title")}
          description={
            error ? t("loadError.description") : t("adminDisabled.description")
          }
        />
      </Section>
    </SettingsSection>
  );
}
