"use client";

import { useState, useEffect, useMemo } from "react";
import {
  track,
  AnalyticsEvent,
  LLMProviderConfiguredSource,
} from "@/lib/analytics/utils";
import { SvgArrowRight, SvgArrowLeft, SvgX } from "@opal/icons";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import {
  OnboardingModalMode,
  OnboardingStep,
} from "@/app/craft/onboarding/types";
import { LLMProviderDescriptor } from "@/lib/languageModels/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { testApiKeyHelper } from "@/sections/modals/languageModels/svc";
import OnboardingInfoPages from "@/app/craft/onboarding/components/OnboardingInfoPages";
import OnboardingLlmSetup, {
  type ProviderKey,
} from "@/app/craft/onboarding/components/OnboardingLlmSetup";
import { craftModelName } from "@/app/craft/onboarding/constants";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";
import { getProvider } from "@/lib/languageModels";

interface BuildOnboardingModalProps {
  mode: OnboardingModalMode;
  llmProviders?: LLMProviderDescriptor[];
  isAdmin: boolean;
  hasAnyProvider: boolean;
  onComplete: () => Promise<void>;
  onLlmComplete: () => Promise<void>;
  onClose: () => void;
}

// Helper to compute steps for mode
function getStepsForMode(
  mode: OnboardingModalMode,
  isAdmin: boolean,
  hasAnyProvider: boolean
): OnboardingStep[] {
  switch (mode.type) {
    case "initial-onboarding": {
      // Full flow: page1 → llm-setup (if admin + no provider yet)
      const steps: OnboardingStep[] = ["page1"];

      if (isAdmin && !hasAnyProvider) {
        steps.push("llm-setup");
      }

      return steps;
    }

    case "add-llm":
      return ["llm-setup"];

    case "closed":
      return [];
  }
}

export default function BuildOnboardingModal({
  mode,
  llmProviders,
  isAdmin,
  hasAnyProvider,
  onComplete,
  onLlmComplete,
  onClose,
}: BuildOnboardingModalProps) {
  // Compute steps based on mode
  const steps = useMemo(
    () => getStepsForMode(mode, isAdmin, hasAnyProvider),
    [mode, isAdmin, hasAnyProvider]
  );

  // Determine initial step based on mode
  const initialStep = useMemo((): OnboardingStep => {
    if (mode.type === "add-llm") return "llm-setup";
    return steps[0] || "page1";
  }, [mode.type, steps]);

  // Navigation state
  const [currentStep, setCurrentStep] = useState<OnboardingStep>(initialStep);

  // Reset step when mode changes
  useEffect(() => {
    if (mode.type !== "closed") {
      setCurrentStep(initialStep);
    }
  }, [mode.type, initialStep]);

  // Determine initial provider for add-llm mode
  const initialProvider = mode.type === "add-llm" ? mode.provider : undefined;

  const { llmProviderOptions } = useLLMProviderOptions();

  const knownModelsFor = (providerType: string) =>
    llmProviderOptions?.find((o) => o.name === providerType)?.known_models ??
    [];

  // LLM setup state
  const [selectedProvider, setSelectedProvider] = useState<ProviderKey>(
    (initialProvider as ProviderKey) || "anthropic"
  );
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [apiKey, setApiKey] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<
    "idle" | "testing" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = useState("");

  // Seed the default model once options load; skip if the user chose one.
  useEffect(() => {
    if (selectedModel) return;
    const def = craftModelName(knownModelsFor(selectedProvider));
    if (def) setSelectedModel(def);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [llmProviderOptions, selectedProvider, selectedModel]);

  // Reset LLM state on add-llm mode change; the seed effect above fills the
  // model for the new provider (clearing it triggers that effect).
  useEffect(() => {
    if (mode.type === "add-llm" && mode.provider) {
      setSelectedProvider(mode.provider as ProviderKey);
      setSelectedModel("");
      setApiKey("");
      setConnectionStatus("idle");
      setErrorMessage("");
    }
  }, [mode]);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);

  const currentProviderLabel = getProvider(selectedProvider).companyName;
  const currentProviderModels = knownModelsFor(selectedProvider).filter(
    (m) => m.is_visible
  );
  const isLlmValid = apiKey.trim() && selectedModel;

  // Calculate step navigation
  const currentStepIndex = steps.indexOf(currentStep);
  const totalSteps = steps.length;

  const handleNext = () => {
    setErrorMessage("");
    const nextIndex = currentStepIndex + 1;
    if (nextIndex < steps.length) {
      setCurrentStep(steps[nextIndex]!);
    }
  };

  const handleBack = () => {
    setErrorMessage("");
    const prevIndex = currentStepIndex - 1;
    if (prevIndex >= 0) {
      setCurrentStep(steps[prevIndex]!);
    }
  };

  const handleConnect = async () => {
    if (!apiKey.trim()) return;

    setConnectionStatus("testing");
    setErrorMessage("");

    const providerName = currentProviderLabel;
    const payload = {
      name: providerName,
      provider: selectedProvider,
      api_key: apiKey,
      default_model_name: selectedModel,
      model_configurations: currentProviderModels.map((m) => ({
        name: m.name,
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
      })),
    };

    const testResult = await testApiKeyHelper(
      selectedProvider,
      payload,
      apiKey,
      selectedModel
    );

    if (!testResult.ok) {
      setErrorMessage(
        "There was an issue with this provider and model, please try a different one."
      );
      setConnectionStatus("error");
      return;
    }

    try {
      const response = await fetch(
        `${SWR_KEYS.adminLlmProviders}?is_creation=true`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        // Surface the backend detail (e.g. a name collision) so the user gets
        // an actionable message instead of a generic failure.
        const detail = await response
          .json()
          .then((b) => (typeof b?.detail === "string" ? b.detail : null))
          .catch(() => null);
        const isConflict = response.status === 409 || response.status === 400;
        setErrorMessage(
          detail ??
            (isConflict
              ? `A provider named "${providerName}" already exists — remove or rename it in Admin → LLM Providers, then retry.`
              : "There was an issue creating the provider. Please try again.")
        );
        setConnectionStatus("error");
        return;
      }

      if (!llmProviders || llmProviders.length === 0) {
        const newProvider = await response.json();
        if (newProvider?.id) {
          await fetch(
            `${SWR_KEYS.adminLlmProviders}/${newProvider.id}/default`,
            {
              method: "POST",
            }
          );
        }
      }

      track(AnalyticsEvent.CONFIGURED_LLM_PROVIDER, {
        provider: selectedProvider,
        is_creation: true,
        source: LLMProviderConfiguredSource.CRAFT_ONBOARDING,
      });

      setConnectionStatus("success");
    } catch (error) {
      console.error("Error connecting LLM provider:", error);
      setErrorMessage(
        "There was an issue connecting the provider. Please try again."
      );
      setConnectionStatus("error");
    }
  };

  const handleSubmit = async () => {
    // For add-llm mode, just close after successful connection
    if (mode.type === "add-llm") {
      if (connectionStatus === "success") {
        await onLlmComplete();
        onClose();
      }
      return;
    }

    // Initial onboarding completion. If LLM setup was part of the flow and the
    // user has no providers (can't skip), require a successful connection.
    if (
      steps.includes("llm-setup") &&
      !hasAnyProvider &&
      connectionStatus !== "success"
    )
      return;

    setIsSubmitting(true);

    try {
      // Refresh LLM providers if LLM was set up
      if (steps.includes("llm-setup") && connectionStatus === "success") {
        await onLlmComplete();
      }

      await onComplete();

      track(AnalyticsEvent.COMPLETED_CRAFT_ONBOARDING);
      onClose();
    } catch (error) {
      console.error("Error completing onboarding:", error);
      setErrorMessage(
        "There was an issue completing onboarding. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  if (mode.type === "closed") return null;

  const isConnecting = connectionStatus === "testing";
  const canTestConnection = isLlmValid && !isConnecting;
  const isLastStep = currentStepIndex === steps.length - 1;
  const isFirstStep = currentStepIndex === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-xs" />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        {/* Close button for add-llm mode */}
        {mode.type === "add-llm" && (
          <button
            type="button"
            onClick={onClose}
            className="absolute top-4 right-4 z-10 p-1 rounded-08 text-text-03 hover:text-text-05 hover:bg-background-tint-02 transition-colors"
          >
            <SvgX className="w-5 h-5" />
          </button>
        )}
        <div className="p-6 flex flex-col gap-6 min-h-[600px]">
          {/* LLM Setup Step */}
          {currentStep === "llm-setup" && (
            <OnboardingLlmSetup
              selectedProvider={selectedProvider}
              selectedModel={selectedModel}
              apiKey={apiKey}
              connectionStatus={connectionStatus}
              errorMessage={errorMessage}
              llmProviders={llmProviders}
              onProviderChange={setSelectedProvider}
              onModelChange={setSelectedModel}
              onApiKeyChange={setApiKey}
              onConnectionStatusChange={setConnectionStatus}
              onErrorMessageChange={setErrorMessage}
            />
          )}

          {/* Page 1 - What is Onyx Craft? */}
          {currentStep === "page1" && <OnboardingInfoPages step="page1" />}

          {/* Navigation buttons */}
          <div className="relative flex justify-between items-center pt-2">
            {/* Back button */}
            <div>
              {!isFirstStep && (
                <button
                  type="button"
                  onClick={handleBack}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-12 border border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-02 transition-colors"
                >
                  <SvgArrowLeft className="w-4 h-4" />
                  <Text font="main-ui-action" color="text-05">
                    Back
                  </Text>
                </button>
              )}
            </div>

            {/* Step indicator */}
            {totalSteps > 1 && (
              <div className="absolute left-1/2 -translate-x-1/2 flex items-center justify-center gap-2">
                {Array.from({ length: totalSteps }).map((_, i) => (
                  <div
                    key={i}
                    className={cn(
                      "w-2 h-2 rounded-full transition-colors",
                      i === currentStepIndex
                        ? "bg-text-05"
                        : i < currentStepIndex
                          ? "bg-text-03"
                          : "bg-border-01"
                    )}
                  />
                ))}
              </div>
            )}

            {/* Action buttons */}
            {currentStep === "page1" && (
              <button
                type="button"
                onClick={isLastStep ? handleSubmit : handleNext}
                disabled={isSubmitting}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                  !isSubmitting
                    ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                    : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
                )}
              >
                <Text
                  font="main-ui-action"
                  color={!isSubmitting ? "text-inverted-05" : "text-02"}
                >
                  {isLastStep
                    ? isSubmitting
                      ? "Saving..."
                      : "Get Started!"
                    : "Continue"}
                </Text>
                {!isLastStep && (
                  <SvgArrowRight className="w-4 h-4 text-white dark:text-black" />
                )}
              </button>
            )}

            {currentStep === "llm-setup" && connectionStatus !== "success" && (
              <div className="flex items-center gap-2">
                {/* Skip button - only shown if user has at least one provider */}
                {hasAnyProvider && !isLastStep && (
                  <button
                    type="button"
                    onClick={handleNext}
                    disabled={isConnecting}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-12 border border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-02 transition-colors"
                  >
                    <Text font="main-ui-action" color="text-05">
                      Skip
                    </Text>
                    <SvgArrowRight className="w-4 h-4" />
                  </button>
                )}
                {/* Connect button */}
                <button
                  type="button"
                  onClick={handleConnect}
                  disabled={!canTestConnection || isConnecting}
                  className={cn(
                    "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                    canTestConnection && !isConnecting
                      ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                      : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
                  )}
                >
                  <Text
                    font="main-ui-action"
                    color={
                      canTestConnection && !isConnecting
                        ? "text-inverted-05"
                        : "text-02"
                    }
                  >
                    {isConnecting ? "Connecting..." : "Connect"}
                  </Text>
                </button>
              </div>
            )}

            {currentStep === "llm-setup" && connectionStatus === "success" && (
              <button
                type="button"
                onClick={isLastStep ? handleSubmit : handleNext}
                className="flex items-center gap-1.5 px-4 py-2 rounded-12 bg-black dark:bg-white text-white dark:text-black hover:opacity-90 transition-colors"
              >
                <Text font="main-ui-action" color="text-inverted-05">
                  {isLastStep ? "Done" : "Continue"}
                </Text>
                {!isLastStep && (
                  <SvgArrowRight className="w-4 h-4 text-white dark:text-black" />
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
