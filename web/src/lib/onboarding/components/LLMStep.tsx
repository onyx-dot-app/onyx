"use client";

import { memo, useState, useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Button, SelectCard } from "@opal/components";
import { noProp } from "@/lib/utils";
import LLMProviderCard from "@/lib/onboarding/components/LLMProviderCard";
import { OnboardingActions, OnboardingState } from "@/lib/onboarding/types";
import { WellKnownLLMProviderDescriptor } from "@/lib/languageModels/types";
import { getProvider } from "@/lib/languageModels/utils";
import {
  useAdminLanguageModel,
  useAdminLanguageModels,
} from "@/lib/languageModels/hooks";
import { useProviderNames } from "@/lib/languageModels/useProviderNames";
import ProviderSetupModal from "@/sections/modals/languageModels/ProviderSetupModal";
import { Disabled } from "@opal/core";
import {
  SvgArrowExchange,
  SvgCpu,
  SvgExternalLink,
  SvgMoreHorizontal,
} from "@opal/icons";
import { CardGrid, ContentAction } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import { ONBOARDING_LLM_PROVIDERS } from "@/lib/onboarding/constants";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";
import { useSettings } from "@/lib/settings/hooks";

interface SelectedProvider {
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  isCustomProvider: boolean;
}

interface LLMStepProps {
  state: OnboardingState;
  actions: OnboardingActions;
  disabled?: boolean;
}
const LLMStep = memo(
  ({
    state: onboardingState,
    actions: onboardingActions,
    disabled,
  }: LLMStepProps) => {
    const t = useTranslations("onboarding");
    const providerNames = useProviderNames();
    const { appName } = useSettings();
    const { llmProviderOptions, isLoading } = useLLMProviderOptions();
    // The onboarding subset, in its order; the rest are in the admin panel.
    const onboardingProviders = ONBOARDING_LLM_PROVIDERS.flatMap((name) => {
      const descriptor = llmProviderOptions?.find(
        (option) => option.name === name
      );
      return descriptor ? [descriptor] : [];
    });
    const openAdminPanel = () => {
      window.location.href = ADMIN_ROUTES.LLM_MODELS.path;
    };

    // A connected provider's settings open its own modal, in edit mode, as on
    // the Language Models admin page. The modal needs the full provider (every
    // model), which loads on demand.
    const { llmProviders: configuredProviders } = useAdminLanguageModels();
    const [editingProviderId, setEditingProviderId] = useState<number | null>(
      null
    );
    const editingProviderQuery = useAdminLanguageModel(editingProviderId);
    const editingProvider = editingProviderQuery.llmProvider;
    // SWR types its error as any; only whether it failed matters here.
    const editingProviderFailed = Boolean(editingProviderQuery.error);
    const EditModal = editingProvider
      ? getProvider(editingProvider.provider).Modal
      : null;
    const openProviderSettings = (name: string) => {
      const configured = configuredProviders?.find(
        (provider) => provider.provider === name
      );
      if (configured) setEditingProviderId(configured.id);
      else openAdminPanel();
    };
    useEffect(() => {
      // When the provider cannot load, the admin page is the fallback.
      if (editingProviderFailed) {
        setEditingProviderId(null);
        openAdminPanel();
      }
    }, [editingProviderFailed]);

    const [selectedProvider, setSelectedProvider] =
      useState<SelectedProvider | null>(null);
    const [isModalOpen, setIsModalOpen] = useState(false);
    // The provider list starts open; the header opens and closes it.
    const [providersOpen, setProvidersOpen] = useState(true);

    const handleProviderClick = useCallback(
      (
        llmDescriptor?: WellKnownLLMProviderDescriptor,
        isCustomProvider: boolean = false
      ) => {
        setSelectedProvider({ llmDescriptor, isCustomProvider });
        setIsModalOpen(true);
      },
      []
    );

    const handleModalClose = useCallback((open: boolean) => {
      setIsModalOpen(open);
      if (!open) {
        setSelectedProvider(null);
      }
    }, []);

    const providerName = selectedProvider?.isCustomProvider
      ? "custom"
      : (selectedProvider?.llmDescriptor?.name ?? "custom");

    return (
      <Disabled disabled={disabled} allowClick>
        <SelectCard
          expandable
          expanded={providersOpen}
          expandableContentHeight="full"
          state="filled"
          onClick={() => setProvidersOpen((open) => !open)}
          expandedContent={
            <div className="p-1">
              {/* Render the selected provider form */}
              <ProviderSetupModal
                providerKey={
                  selectedProvider && isModalOpen ? providerName : null
                }
                shouldMarkAsDefault={
                  (onboardingState?.data.llmProviders ?? []).length === 0
                }
                onboardingActions={onboardingActions}
                onOpenChange={handleModalClose}
                onSuccess={() => {
                  onboardingActions.updateData({
                    llmProviders: [
                      ...(onboardingState?.data.llmProviders ?? []),
                      providerName,
                    ],
                  });
                  onboardingActions.setButtonActive(true);
                }}
              />
              {EditModal && editingProvider && (
                <EditModal
                  existingLlmProvider={editingProvider}
                  onOpenChange={(open) => {
                    if (!open) setEditingProviderId(null);
                  }}
                />
              )}
              <CardGrid gap={1}>
                {isLoading
                  ? Array.from(
                      { length: ONBOARDING_LLM_PROVIDERS.length + 1 },
                      (_, idx) => (
                        <CardLoader key={idx} padding={2} rounding={3} />
                      )
                    )
                  : onboardingProviders.map((llmDescriptor) => {
                      const provider = getProvider(llmDescriptor.name);
                      const { productName, companyName } =
                        providerNames(provider);
                      const isConnected =
                        onboardingState.data.llmProviders?.includes(
                          llmDescriptor.name
                        ) ?? false;
                      return (
                        <LLMProviderCard
                          key={llmDescriptor.name}
                          icon={provider.icon}
                          title={productName}
                          description={companyName}
                          actionLabel={t("llmStep.providerCard.connect.label")}
                          actionIcon={SvgArrowExchange}
                          isConnected={isConnected}
                          onClick={() =>
                            isConnected
                              ? openAdminPanel()
                              : handleProviderClick(llmDescriptor, false)
                          }
                          onSettingsClick={() =>
                            openProviderSettings(llmDescriptor.name)
                          }
                        />
                      );
                    })}
                {!isLoading && (
                  // Spans both columns, closing the grid as one wide row.
                  <div className="col-span-full">
                    <LLMProviderCard
                      icon={SvgMoreHorizontal}
                      title={t("llmStep.moreProviders.title")}
                      description={t("llmStep.moreProviders.description")}
                      actionLabel={t("llmStep.moreProviders.button.label")}
                      actionIcon={SvgExternalLink}
                      onClick={openAdminPanel}
                    />
                  </div>
                )}
              </CardGrid>
            </div>
          }
          rounding={4}
          padding={1}
          aria-label="onboarding-llm-step"
        >
          <ContentAction
            icon={SvgCpu}
            title={t("llmStep.title")}
            description={t("llmStep.description", { appName })}
            sizePreset="main-ui"
            variant="section"
            padding={2}
            rightChildren={
              <Button
                disabled={disabled}
                prominence="internal"
                rightIcon={SvgExternalLink}
                href={ADMIN_ROUTES.LLM_MODELS.path}
                // The link opens the admin page, not the card's provider list.
                onClick={noProp()}
              >
                {t("llmStep.adminPanel.label")}
              </Button>
            }
          />
        </SelectCard>
      </Disabled>
    );
  }
);
LLMStep.displayName = "LLMStep";

export default LLMStep;
