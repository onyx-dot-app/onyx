import { memo, useState, useCallback } from "react";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Separator from "@/refresh-components/Separator";
import LLMProviderCard from "../components/LLMProviderCard";
import { OnboardingActions, OnboardingState, OnboardingStep } from "../types";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  getOnboardingForm,
  getProviderDisplayInfo,
} from "../forms/getOnboardingForm";
import { cn } from "@/lib/utils";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";
import { SvgCheckCircle, SvgCpu, SvgExternalLink } from "@opal/icons";

type LLMStepProps = {
  state: OnboardingState;
  actions: OnboardingActions;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
  disabled?: boolean;
};

interface SelectedProvider {
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  isCustomProvider: boolean;
}

const LLMProviderSkeleton = () => {
  return (
    <div className="flex justify-between h-full w-full p-1 rounded-12 border border-border-01 bg-background-neutral-01 animate-pulse">
      <div className="flex gap-1 p-1 flex-1 min-w-0">
        <div className="h-full p-0.5">
          <div className="w-4 h-4 rounded-full bg-neutral-200" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="h-3 w-1/2 bg-neutral-200 rounded" />
          <div className="mt-2 h-2 w-3/4 bg-neutral-200 rounded" />
        </div>
      </div>
      <div className="h-6 w-16 bg-neutral-200 rounded" />
    </div>
  );
};

type StackedProviderIconsProps = {
  providers: string[];
};

const StackedProviderIcons = ({ providers }: StackedProviderIconsProps) => {
  if (!providers || providers.length === 0) {
    return null;
  }

  return (
    <div className="flex items-center">
      {providers.slice(0, 3).map((provider, index) => (
        <div
          key={provider}
          className="relative flex items-center justify-center w-6 h-6 rounded-04 bg-background-neutral-01 border border-border-01"
          style={{
            marginLeft: index > 0 ? "-8px" : "0",
            zIndex: providers.length - index,
          }}
        >
          <ProviderIcon provider={provider} size={16} />
        </div>
      ))}
      {providers.length > 3 && (
        <div
          className="relative flex items-center justify-center w-6 h-6 rounded-04 bg-background-neutral-01 border border-border-01"
          style={{
            marginLeft: "-8px",
            zIndex: 0,
          }}
        >
          <Text as="p" text03 secondaryBody>
            +{providers.length - 3}
          </Text>
        </div>
      )}
    </div>
  );
};

const LLMStepInner = ({
  state: onboardingState,
  actions: onboardingActions,
  llmDescriptors,
  disabled,
}: LLMStepProps) => {
  const isLoading = !llmDescriptors || llmDescriptors.length === 0;

  const [selectedProvider, setSelectedProvider] =
    useState<SelectedProvider | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

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

  if (
    onboardingState.currentStep === OnboardingStep.LlmSetup ||
    onboardingState.currentStep === OnboardingStep.Name
  ) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-between w-full max-w-[800px] p-1 rounded-16 border border-border-01 bg-background-tint-00",
          disabled && "opacity-50 pointer-events-none select-none"
        )}
      >
        <div className="flex gap-2 justify-between h-full w-full">
          <div className="flex mx-2 mt-2 gap-1">
            <div className="h-full p-0.5">
              <SvgCpu className="w-4 h-4 stroke-text-03" />
            </div>
            <div>
              <Text as="p" text04 mainUiAction>
                Connect your LLM models
              </Text>
              <Text as="p" text03 secondaryBody>
                Onyx supports both self-hosted models and popular providers.
              </Text>
            </div>
          </div>
          <div className="p-0.5">
            <Button
              tertiary
              rightIcon={SvgExternalLink}
              disabled={disabled}
              href="admin/configuration/llm"
            >
              View in Admin Panel
            </Button>
          </div>
        </div>
        <Separator />
        <div className="flex flex-wrap gap-1 [&>*:last-child:nth-child(odd)]:basis-full">
          {isLoading ? (
            Array.from({ length: 8 }).map((_, idx) => (
              <div
                key={idx}
                className="basis-[calc(50%-theme(spacing.1)/2)] grow"
              >
                <LLMProviderSkeleton />
              </div>
            ))
          ) : (
            <>
              {/* Render the selected provider form */}
              {selectedProvider &&
                getOnboardingForm({
                  llmDescriptor: selectedProvider.llmDescriptor,
                  isCustomProvider: selectedProvider.isCustomProvider,
                  onboardingState,
                  onboardingActions,
                  open: isModalOpen,
                  onOpenChange: handleModalClose,
                })}

              {/* Render provider cards */}
              {llmDescriptors.map((llmDescriptor) => {
                const displayInfo = getProviderDisplayInfo(llmDescriptor.name);
                return (
                  <div
                    key={llmDescriptor.name}
                    className="basis-[calc(50%-theme(spacing.1)/2)] grow"
                  >
                    <LLMProviderCard
                      title={displayInfo.title}
                      subtitle={displayInfo.displayName}
                      providerName={llmDescriptor.name}
                      disabled={disabled}
                      isConnected={onboardingState.data.llmProviders?.some(
                        (provider) => provider === llmDescriptor.name
                      )}
                      onClick={() => handleProviderClick(llmDescriptor, false)}
                    />
                  </div>
                );
              })}

              {/* Custom provider card */}
              <div className="basis-[calc(50%-theme(spacing.1)/2)] grow">
                <LLMProviderCard
                  title="Custom LLM Provider"
                  subtitle="LiteLLM Compatible APIs"
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
      </div>
    );
  } else {
    return (
      <button
        type="button"
        className="flex items-center justify-between w-full max-w-[800px] p-3 bg-background-tint-00 rounded-16 border border-border-01 opacity-50"
        onClick={() => {
          onboardingActions.setButtonActive(true);
          onboardingActions.goToStep(OnboardingStep.LlmSetup);
        }}
        aria-label="Edit LLM providers"
      >
        <div className="flex items-center gap-1">
          <StackedProviderIcons
            providers={onboardingState.data.llmProviders || []}
          />
          <Text as="p" text04 mainUiAction>
            {onboardingState.data.llmProviders?.length || 0}{" "}
            {(onboardingState.data.llmProviders?.length || 0) === 1
              ? "model"
              : "models"}{" "}
            connected
          </Text>
        </div>
        <div className="p-1">
          <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
        </div>
      </button>
    );
  }
};

const LLMStep = memo(LLMStepInner);
export default LLMStep;
