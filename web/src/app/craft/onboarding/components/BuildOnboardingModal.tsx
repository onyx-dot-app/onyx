"use client";

import { useState, useEffect, useMemo } from "react";
import { usePostHog } from "posthog-js/react";
import { SvgArrowRight, SvgArrowLeft, SvgX } from "@opal/icons";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import {
  BuildUserInfo,
  OnboardingModalMode,
  OnboardingStep,
} from "@/app/craft/onboarding/types";
import {
  WorkArea,
  Level,
  WORK_AREAS_REQUIRING_LEVEL,
  setBuildLlmSelection,
  getBuildLlmSelection,
  getDefaultLlmSelection,
} from "@/app/craft/onboarding/constants";
import { LLMProviderDescriptor } from "@/interfaces/llm";
import { LLM_PROVIDERS_ADMIN_URL } from "@/lib/llmConfig/constants";
import {
  buildInitialValues,
  testApiKeyHelper,
} from "@/refresh-components/onboarding/components/llmConnectionHelpers";
import OnboardingInfoPages from "@/app/craft/onboarding/components/OnboardingInfoPages";
import OnboardingUserInfo from "@/app/craft/onboarding/components/OnboardingUserInfo";
import OnboardingLlmSetup, {
  PROVIDERS,
  type ProviderKey,
} from "@/app/craft/onboarding/components/OnboardingLlmSetup";

/**
 * Auto-select the best available LLM based on priority order.
 * Used when user completes onboarding without going through LLM setup step.
 */
function autoSelectBestLlm(
  llmProviders: LLMProviderDescriptor[] | undefined
): void {
  // Don't override if user already has a selection
  if (getBuildLlmSelection()) return;

  const selection = getDefaultLlmSelection(llmProviders);
  if (selection) {
    setBuildLlmSelection(selection);
  }
}

interface InitialValues {
  firstName: string;
  lastName: string;
  workArea: WorkArea | undefined;
  level: Level | undefined;
}

interface BuildOnboardingModalProps {
  mode: OnboardingModalMode;
  llmProviders?: LLMProviderDescriptor[];
  initialValues: InitialValues;
  isAdmin: boolean;
  hasUserInfo: boolean;
  allProvidersConfigured: boolean;
  hasAnyProvider: boolean;
  onComplete: (info: BuildUserInfo) => Promise<void>;
  onLlmComplete: () => Promise<void>;
  onClose: () => void;
}

// Helper to compute steps for mode
function getStepsForMode(
  mode: OnboardingModalMode,
  isAdmin: boolean,
  allProvidersConfigured: boolean,
  hasUserInfo: boolean
): OnboardingStep[] {
  switch (mode.type) {
    case "initial-onboarding":
      // Full flow: page1 → llm-setup (if admin + not all configured) → user-info
      const steps: OnboardingStep[] = ["page1"];

      if (isAdmin && !allProvidersConfigured) {
        steps.push("llm-setup");
      }

      if (!hasUserInfo) {
        steps.push("user-info");
      }

      return steps;

    case "edit-persona":
      return ["user-info"];

    case "add-llm":
      return ["llm-setup"];

    case "closed":
      return [];
  }
}

export default function BuildOnboardingModal({
  mode,
  llmProviders,
  initialValues,
  isAdmin,
  hasUserInfo,
  allProvidersConfigured,
  hasAnyProvider,
  onComplete,
  onLlmComplete,
  onClose,
}: BuildOnboardingModalProps) {
  const posthog = usePostHog();

  // Compute steps based on mode
  const steps = useMemo(
    () => getStepsForMode(mode, isAdmin, allProvidersConfigured, hasUserInfo),
    [mode, isAdmin, allProvidersConfigured, hasUserInfo]
  );

  // Determine initial step based on mode
  const initialStep = useMemo((): OnboardingStep => {
    if (mode.type === "add-llm") return "llm-setup";
    return steps[0] || "user-info";
  }, [mode.type, steps]);

  // Navigation state
  const [currentStep, setCurrentStep] = useState<OnboardingStep>(initialStep);

  // Reset step when mode changes
  useEffect(() => {
    if (mode.type !== "closed") {
      setCurrentStep(initialStep);
    }
  }, [mode.type, initialStep]);

  // User info state - pre-fill from initialValues
  const [firstName, setFirstName] = useState(initialValues.firstName);
  const [lastName, setLastName] = useState(initialValues.lastName);
  const [workArea, setWorkArea] = useState(initialValues.workArea);
  const [level, setLevel] = useState(initialValues.level);

  // Update form values when initialValues changes
  useEffect(() => {
    setFirstName(initialValues.firstName);
    setLastName(initialValues.lastName);
    setWorkArea(initialValues.workArea);
    setLevel(initialValues.level);
  }, [initialValues]);

  // Determine initial provider for add-llm mode
  const initialProvider = mode.type === "add-llm" ? mode.provider : undefined;

  // LLM setup state
  const [selectedProvider, setSelectedProvider] = useState<ProviderKey>(
    (initialProvider as ProviderKey) || "anthropic"
  );
  const [selectedModel, setSelectedModel] = useState<string>(
    PROVIDERS.find((p) => p.key === (initialProvider || "anthropic"))?.models[0]
      ?.name || ""
  );
  const [apiKey, setApiKey] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<
    "idle" | "testing" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = useState("");

  // Reset LLM state when mode changes to add-llm with a specific provider
  useEffect(() => {
    if (mode.type === "add-llm" && mode.provider) {
      const providerConfig = PROVIDERS.find(
        (p) => p.key === (mode.provider as ProviderKey)
      );
      if (providerConfig) {
        setSelectedProvider(providerConfig.key);
        setSelectedModel(providerConfig.models[0]?.name || "");
        setApiKey("");
        setConnectionStatus("idle");
        setErrorMessage("");
      }
    }
  }, [mode]);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);

  const requiresLevel =
    workArea !== undefined && WORK_AREAS_REQUIRING_LEVEL.includes(workArea);
  const isUserInfoValid = workArea && (!requiresLevel || level);

  const currentProviderConfig = PROVIDERS.find(
    (p) => p.key === selectedProvider
  )!;
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

    const baseValues = buildInitialValues();
    const providerName = `build-mode-${currentProviderConfig.providerName}`;
    const payload = {
      ...baseValues,
      name: providerName,
      provider: currentProviderConfig.providerName,
      api_key: apiKey,
      default_model_name: selectedModel,
      model_configurations: currentProviderConfig.models.map((m) => ({
        name: m.name,
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
      })),
    };

    const testResult = await testApiKeyHelper(
      currentProviderConfig.providerName,
      payload
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
        `${LLM_PROVIDERS_ADMIN_URL}?is_creation=true`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        setErrorMessage(
          "There was an issue creating the provider. Please try again."
        );
        setConnectionStatus("error");
        return;
      }

      if (!llmProviders || llmProviders.length === 0) {
        const newProvider = await response.json();
        if (newProvider?.id) {
          await fetch(`${LLM_PROVIDERS_ADMIN_URL}/${newProvider.id}/default`, {
            method: "POST",
          });
        }
      }

      setBuildLlmSelection({
        providerName: providerName,
        provider: currentProviderConfig.providerName,
        modelName: selectedModel,
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

    if (!isUserInfoValid) return;
    // If LLM setup was part of the flow and user has no providers (can't skip), require completion
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

      // Auto-select best available LLM if user didn't go through LLM setup
      // (e.g., non-admin users or when all providers already configured)
      autoSelectBestLlm(llmProviders);

      // Validate workArea is provided before submission
      if (!workArea) {
        setErrorMessage("Please select a work area.");
        setIsSubmitting(false);
        return;
      }

      const requiresLevel = WORK_AREAS_REQUIRING_LEVEL.includes(workArea);

      // Validate level if required
      if (requiresLevel && !level) {
        setErrorMessage("Please select a level.");
        setIsSubmitting(false);
        return;
      }

      await onComplete({
        firstName: firstName.trim(),
        lastName: lastName.trim() || undefined,
        workArea,
        level: level || undefined,
      });

      posthog?.capture("completed_craft_onboarding");
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

  const canProceedUserInfo = isUserInfoValid;
  const isConnecting = connectionStatus === "testing";
  const canTestConnection = isLlmValid && !isConnecting;
  const isLastStep = currentStepIndex === steps.length - 1;
  const isFirstStep = currentStepIndex === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

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
          {/* User Info Step */}
          {currentStep === "user-info" && (
            <OnboardingUserInfo
              firstName={firstName}
              lastName={lastName}
              workArea={workArea}
              level={level}
              onFirstNameChange={setFirstName}
              onLastNameChange={setLastName}
              onWorkAreaChange={setWorkArea}
              onLevelChange={setLevel}
            />
          )}

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
          {currentStep === "page1" && (
            <OnboardingInfoPages
              step="page1"
              workArea={workArea}
              level={level}
            />
          )}

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
                  <Text mainUiAction>Back</Text>
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
            {currentStep === "user-info" && (
              <button
                type="button"
                onClick={() => {
                  posthog?.capture("completed_craft_user_info", {
                    first_name: firstName.trim(),
                    last_name: lastName.trim() || undefined,
                    work_area: workArea,
                    level: level,
                  });
                  if (isLastStep) {
                    handleSubmit();
                  } else {
                    handleNext();
                  }
                }}
                disabled={!canProceedUserInfo || isSubmitting}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                  canProceedUserInfo && !isSubmitting
                    ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                    : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
                )}
              >
                <Text
                  mainUiAction
                  className={cn(
                    canProceedUserInfo && !isSubmitting
                      ? "text-white dark:text-black"
                      : "text-text-02"
                  )}
                >
                  {isLastStep
                    ? isSubmitting
                      ? "Saving..."
                      : "Get Started!"
                    : "Continue"}
                </Text>
                {!isLastStep && (
                  <SvgArrowRight
                    className={cn(
                      "w-4 h-4",
                      canProceedUserInfo && !isSubmitting
                        ? "text-white dark:text-black"
                        : "text-text-02"
                    )}
                  />
                )}
              </button>
            )}

            {currentStep === "page1" && (
              <button
                type="button"
                onClick={handleNext}
                className="flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
              >
                <Text mainUiAction className="text-white dark:text-black">
                  Continue
                </Text>
                <SvgArrowRight className="w-4 h-4 text-white dark:text-black" />
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
                    <Text mainUiAction>Skip</Text>
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
                    mainUiAction
                    className={cn(
                      canTestConnection && !isConnecting
                        ? "text-white dark:text-black"
                        : "text-text-02"
                    )}
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
                <Text mainUiAction className="text-white dark:text-black">
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
