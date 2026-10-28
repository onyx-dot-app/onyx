"use client";

import { memo, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Button, SelectCard } from "@opal/components";
import { noProp } from "@/lib/utils";
import LLMProviderCard from "@/lib/onboarding/components/LLMProviderCard";
import { OnboardingActions, OnboardingState } from "@/lib/onboarding/types";
import { WellKnownLLMProviderDescriptor } from "@/lib/languageModels/types";
import { getProvider } from "@/lib/languageModels/utils";
import { useProviderNames } from "@/lib/languageModels/useProviderNames";
import ProviderSetupModal from "@/sections/modals/languageModels/ProviderSetupModal";
import { Disabled } from "@opal/core";
import { SvgCpu, SvgExternalLink } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";
import { useSettings } from "@/lib/settings/hooks";

interface SelectedProvider {
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  isCustomProvider: boolean;
}

function LLMProviderSkeleton() {
  return (
    <div className="flex justify-between h-full w-full p-1 rounded-12 border border-border-01 bg-background-neutral-01 animate-pulse">
      <div className="flex gap-1 p-1 flex-1 min-w-0">
        <div className="h-full p-0.5">
          <div className="w-4 h-4 rounded-full bg-neutral-200" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="h-3 w-1/2 bg-neutral-200 rounded-sm" />
          <div className="mt-2 h-2 w-3/4 bg-neutral-200 rounded-sm" />
        </div>
      </div>
      <div className="h-6 w-16 bg-neutral-200 rounded-sm" />
    </div>
  );
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
    const llmDescriptors = llmProviderOptions ?? [];

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
            <div className="@container/llmcards flex flex-wrap gap-1 w-full p-1 [&>*:last-child:nth-child(odd)]:basis-full">
              {isLoading ? (
                Array.from({ length: 8 }).map((_, idx) => (
                  <div
                    key={idx}
                    className="basis-full @xl/llmcards:basis-[calc(50%-(--spacing(1))/2)] grow"
                  >
                    <LLMProviderSkeleton />
                  </div>
                ))
              ) : (
                <>
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

                  {/* Render provider cards */}
                  {llmDescriptors.map((llmDescriptor) => {
                    const { productName, companyName } = providerNames(
                      getProvider(llmDescriptor.name)
                    );
                    return (
                      <div
                        key={llmDescriptor.name}
                        className="basis-full @xl/llmcards:basis-[calc(50%-(--spacing(1))/2)] grow"
                      >
                        <LLMProviderCard
                          title={productName}
                          subtitle={companyName}
                          providerName={llmDescriptor.name}
                          disabled={disabled}
                          isConnected={onboardingState.data.llmProviders?.some(
                            (provider) => provider === llmDescriptor.name
                          )}
                          onClick={() =>
                            handleProviderClick(llmDescriptor, false)
                          }
                        />
                      </div>
                    );
                  })}

                  {/* Custom provider card */}
                  <div className="basis-full @xl/llmcards:basis-[calc(50%-(--spacing(1))/2)] grow">
                    <LLMProviderCard
                      title={t("llmStep.customProvider.title")}
                      subtitle={t("llmStep.customProvider.subtitle")}
                      disabled={disabled}
                      isConnected={onboardingState.data.llmProviders?.some(
                        (provider) => provider === "custom"
                      )}
                      onClick={() => handleProviderClick(undefined, true)}
                    />
                  </div>
                </>
              )}
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
