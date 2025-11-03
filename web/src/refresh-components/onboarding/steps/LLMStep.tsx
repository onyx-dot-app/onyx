import React, { memo, useEffect } from "react";
import SvgCpu from "@/icons/cpu";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import SvgExternalLink from "@/icons/external-link";
import { Separator } from "@/components/ui/separator";
import LLMProvider from "../components/LLMProvider";
import { OnboardingActions, OnboardingState, OnboardingStep } from "../types";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { PROVIDER_ICON_MAP } from "../constants";
import LLMConnectionModal from "@/refresh-components/onboarding/components/LLMConnectionModal";
import KeyValueInput from "@/refresh-components/inputs/InputKeyValue";
import { cn } from "@/lib/utils";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import SvgCheckCircle from "@/icons/check-circle";

type LLMStepProps = {
  state: OnboardingState;
  actions: OnboardingActions;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
  disabled?: boolean;
};

const LLMProviderSkeleton = () => {
  return (
    <div className="flex justify-between h-full w-full p-1 rounded-12 border border-border-01 bg-background-neutral-01 animate-pulse">
      <div className="flex gap-1 p-1 flex-1 min-w-0">
        <div className="h-full p-0.5">
          <div className="w-4 h-4 rounded-full bg-neutral-200 dark:bg-neutral-700" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="h-3 w-1/2 bg-neutral-200 dark:bg-neutral-700 rounded" />
          <div className="mt-2 h-2 w-3/4 bg-neutral-200 dark:bg-neutral-700 rounded" />
        </div>
      </div>
      <div className="h-6 w-16 bg-neutral-200 dark:bg-neutral-700 rounded" />
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
      {providers.slice(0, 3).map((provider, index) => {
        const IconComponent = PROVIDER_ICON_MAP[provider];
        if (!IconComponent) return null;

        return (
          <div
            key={provider}
            className="relative flex items-center justify-center w-6 h-6 rounded-04 bg-background-neutral-01 border border-border-01"
            style={{
              marginLeft: index > 0 ? "-8px" : "0",
              zIndex: providers.length - index,
            }}
          >
            <IconComponent className="w-4 h-4" />
          </div>
        );
      })}
      {providers.length > 3 && (
        <div
          className="relative flex items-center justify-center w-6 h-6 rounded-04 bg-background-neutral-01 border border-border-01"
          style={{
            marginLeft: "-8px",
            zIndex: 0,
          }}
        >
          <Text text03 secondaryBody>
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
              <Text text04 mainUiAction>
                Connect your LLM models
              </Text>
              <Text text03 secondaryBody>
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

        <div className="p-2 w-full">
          <Separator className="my-2" />
        </div>
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
              {llmDescriptors.map((llmDescriptor) => (
                <div
                  key={llmDescriptor.name}
                  className="basis-[calc(50%-theme(spacing.1)/2)] grow"
                >
                  <LLMProvider
                    onboardingState={onboardingState}
                    onboardingActions={onboardingActions}
                    title={llmDescriptor.title}
                    subtitle={llmDescriptor.display_name}
                    icon={PROVIDER_ICON_MAP[llmDescriptor.name]}
                    llmDescriptor={llmDescriptor}
                    disabled={disabled}
                    isConnected={onboardingState.data.llmProviders?.some(
                      (provider) => provider === llmDescriptor.name
                    )}
                  />
                </div>
              ))}

              <div className="basis-[calc(50%-theme(spacing.1)/2)] grow">
                <LLMProvider
                  onboardingState={onboardingState}
                  onboardingActions={onboardingActions}
                  title="Custom LLM Provider"
                  subtitle="LiteLLM Compatible APIs"
                  disabled={disabled}
                  isConnected={onboardingState.data.llmProviders?.some(
                    (provider) => provider === "custom"
                  )}
                />
              </div>
            </>
          )}
          <LLMConnectionModal />
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
          <Text text04 mainUiAction>
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
