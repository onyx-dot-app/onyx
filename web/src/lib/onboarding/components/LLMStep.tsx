"use client";

import { useNavigation } from "@opal/navigation";
import { memo, useState, useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Button, SelectCard, useCreateModal } from "@opal/components";
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
import { CardGrid, ContentAction, toast } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import { ONBOARDING_LLM_PROVIDERS } from "@/lib/onboarding/constants";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";
import { useSettings } from "@/lib/settings/hooks";

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
    const navigation = useNavigation();
    const adminPanelLink = navigation.linkTo(ADMIN_ROUTES.LLM_MODELS.path);
    const { llmProviderOptions, isLoading } = useLLMProviderOptions();
    // The onboarding subset, in its order; the rest are in the admin panel.
    const onboardingProviders = ONBOARDING_LLM_PROVIDERS.flatMap((name) => {
      const descriptor = llmProviderOptions?.find(
        (option) => option.name === name
      );
      return descriptor ? [descriptor] : [];
    });
    const openAdminPanel = () => {
      navigation.go(ADMIN_ROUTES.LLM_MODELS.path);
    };

    // A connected provider's settings open the same modal as Connect, on this
    // page, in edit mode. The modal needs the full provider (every model),
    // which loads on demand.
    const { llmProviders: configuredProviders, refetch: refetchProviders } =
      useAdminLanguageModels();
    const [editingProviderId, setEditingProviderId] = useState<number | null>(
      null
    );
    const editModal = useCreateModal();
    const editingProviderQuery = useAdminLanguageModel(
      editModal.isPresent ? editingProviderId : null
    );
    const editingProvider = editingProviderQuery.llmProvider;
    // SWR types its error as any; only whether it failed matters here.
    const editingProviderFailed = Boolean(editingProviderQuery.error);
    const EditModal = editingProvider
      ? getProvider(editingProvider.provider, editingProvider).Modal
      : null;
    const openProviderSettings = async (name: string) => {
      // A provider connected during onboarding is not in the cached list yet,
      // so a miss refetches it before giving up.
      let configuredId = configuredProviders?.find(
        (provider) => provider.provider === name
      )?.id;
      if (configuredId === undefined) {
        try {
          const fresh = await refetchProviders();
          configuredId = fresh?.providers.find(
            (provider) => provider.provider === name
          )?.id;
        } catch {
          toast.error(t("llmStep.providerCard.settingsLoadError"));
          return;
        }
      }
      if (configuredId !== undefined) {
        setEditingProviderId(configuredId);
        editModal.toggle(true);
      }
    };
    useEffect(() => {
      if (!editingProviderFailed) return;
      toast.error(t("llmStep.providerCard.settingsLoadError"));
      editModal.toggle(false);
      setEditingProviderId(null);
    }, [editingProviderFailed, t]);

    const [selectedProvider, setSelectedProvider] =
      useState<WellKnownLLMProviderDescriptor | null>(null);
    const setupModal = useCreateModal();
    const toggleSetupModal = setupModal.toggle;
    // The provider list starts open; the header opens and closes it.
    const [providersOpen, setProvidersOpen] = useState(true);

    const handleProviderClick = useCallback(
      (llmDescriptor: WellKnownLLMProviderDescriptor) => {
        setSelectedProvider(llmDescriptor);
        toggleSetupModal(true);
      },
      [toggleSetupModal]
    );

    // Keeps the selected provider on close so the modal can animate out.
    const handleModalClose = useCallback(
      (open: boolean) => toggleSetupModal(open),
      [toggleSetupModal]
    );

    const providerName = selectedProvider?.name ?? "custom";

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
              <setupModal.Provider>
                <ProviderSetupModal
                  providerKey={selectedProvider ? providerName : null}
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
              </setupModal.Provider>
              <editModal.Provider>
                {EditModal && editingProvider && (
                  <EditModal
                    variant="onboarding"
                    existingLlmProvider={editingProvider}
                    onOpenChange={(open) => {
                      if (!open) editModal.toggle(false);
                    }}
                  />
                )}
              </editModal.Provider>
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
                          // Connected: the card and its settings button both
                          // open the provider's modal in edit mode.
                          onClick={() =>
                            isConnected
                              ? void openProviderSettings(llmDescriptor.name)
                              : handleProviderClick(llmDescriptor)
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
            font="main-ui-action"
            icon={SvgCpu}
            title={t("llmStep.title")}
            description={t("llmStep.description", { appName })}
            padding={2}
            rightChildren={
              <Button
                disabled={disabled}
                prominence="internal"
                rightIcon={SvgExternalLink}
                href={adminPanelLink.href}
                // The link opens the admin page, not the card's provider list.
                onClick={(event) => {
                  event.stopPropagation();
                  adminPanelLink.onClick(event);
                }}
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
