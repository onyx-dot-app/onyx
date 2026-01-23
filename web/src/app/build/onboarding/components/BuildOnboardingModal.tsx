"use client";

import { useState, useEffect, useRef } from "react";
import { SvgInfoSmall, SvgArrowRight, SvgArrowLeft } from "@opal/icons";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { BuildUserInfo } from "@/app/build/onboarding/types";
import {
  WORK_AREA_OPTIONS,
  LEVEL_OPTIONS,
  WORK_AREAS_WITH_LEVEL,
} from "@/app/build/onboarding/constants";
import {
  LLMProviderDescriptor,
  LLMProviderName,
} from "@/app/admin/configuration/llm/interfaces";
import { LLM_PROVIDERS_ADMIN_URL } from "@/app/admin/configuration/llm/constants";
import {
  buildInitialValues,
  testApiKeyHelper,
} from "@/refresh-components/onboarding/components/llmConnectionHelpers";

// Provider configurations
type ProviderKey = "anthropic" | "openai" | "openrouter";

interface ModelOption {
  name: string;
  label: string;
  recommended?: boolean;
}

interface ProviderConfig {
  key: ProviderKey;
  label: string;
  providerName: LLMProviderName;
  recommended?: boolean;
  models: ModelOption[];
  apiKeyPlaceholder: string;
  apiKeyUrl: string;
  apiKeyLabel: string;
}

const PROVIDERS: ProviderConfig[] = [
  {
    key: "anthropic",
    label: "Anthropic",
    providerName: LLMProviderName.ANTHROPIC,
    recommended: true,
    models: [
      { name: "claude-opus-4-5", label: "Claude Opus 4.5", recommended: true },
      { name: "claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
    ],
    apiKeyPlaceholder: "sk-ant-...",
    apiKeyUrl: "https://console.anthropic.com/dashboard",
    apiKeyLabel: "Anthropic Console",
  },
  {
    key: "openai",
    label: "OpenAI",
    providerName: LLMProviderName.OPENAI,
    models: [
      { name: "gpt-5.2", label: "GPT-5.2", recommended: true },
      { name: "gpt-5.1", label: "GPT-5.1" },
    ],
    apiKeyPlaceholder: "sk-...",
    apiKeyUrl: "https://platform.openai.com/api-keys",
    apiKeyLabel: "OpenAI Dashboard",
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    providerName: LLMProviderName.OPENROUTER,
    models: [
      {
        name: "moonshotai/kimi-k2-thinking",
        label: "Kimi K2 Thinking",
        recommended: true,
      },
      { name: "google/gemini-3-pro-preview", label: "Gemini 3 Pro" },
      { name: "qwen/qwen3-235b-a22b-thinking-2507", label: "Qwen3 235B" },
    ],
    apiKeyPlaceholder: "sk-or-...",
    apiKeyUrl: "https://openrouter.ai/keys",
    apiKeyLabel: "OpenRouter Dashboard",
  },
];

type Step = "user-info" | "llm-setup";

interface SelectableButtonProps {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  subtext?: string;
  disabled?: boolean;
}

function SelectableButton({
  selected,
  onClick,
  children,
  subtext,
  disabled,
}: SelectableButtonProps) {
  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "px-6 py-3 rounded-12 border transition-colors",
          disabled && "opacity-50 cursor-not-allowed",
          selected
            ? "border-action-link-05 bg-action-link-01 text-action-text-link-05"
            : "border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-01"
        )}
      >
        <Text mainUiAction>{children}</Text>
      </button>
      {subtext && (
        <Text figureSmallLabel text02>
          {subtext}
        </Text>
      )}
    </div>
  );
}

interface ModelSelectButtonProps {
  selected: boolean;
  onClick: () => void;
  label: string;
  recommended?: boolean;
  disabled?: boolean;
}

function ModelSelectButton({
  selected,
  onClick,
  label,
  recommended,
  disabled,
}: ModelSelectButtonProps) {
  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "px-4 py-2.5 rounded-12 border transition-colors",
          disabled && "opacity-50 cursor-not-allowed",
          selected
            ? "border-action-link-05 bg-action-link-01 text-action-text-link-05"
            : "border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-01"
        )}
      >
        <Text mainUiAction>{label}</Text>
      </button>
      {recommended && (
        <Text figureSmallLabel text02>
          Recommended
        </Text>
      )}
    </div>
  );
}

interface InitialValues {
  firstName: string;
  lastName: string;
  workArea: string;
  level: string;
}

interface BuildOnboardingModalProps {
  open: boolean;
  showLlmSetup: boolean;
  llmProviders?: LLMProviderDescriptor[];
  onComplete: (info: BuildUserInfo) => Promise<void>;
  onLlmComplete?: () => Promise<void>;
  initialValues?: InitialValues;
}

export default function BuildOnboardingModal({
  open,
  showLlmSetup,
  llmProviders,
  onComplete,
  onLlmComplete,
  initialValues,
}: BuildOnboardingModalProps) {
  // Navigation
  const [currentStep, setCurrentStep] = useState<Step>("user-info");

  // User info state - pre-fill from initialValues if available
  const [firstName, setFirstName] = useState(initialValues?.firstName || "");
  const [lastName, setLastName] = useState(initialValues?.lastName || "");
  const [workArea, setWorkArea] = useState(initialValues?.workArea || "");
  const [level, setLevel] = useState(initialValues?.level || "");

  // Update form values if initialValues changes (e.g., after user data loads)
  useEffect(() => {
    if (initialValues) {
      if (initialValues.firstName && !firstName)
        setFirstName(initialValues.firstName);
      if (initialValues.lastName && !lastName)
        setLastName(initialValues.lastName);
      if (initialValues.workArea && !workArea)
        setWorkArea(initialValues.workArea);
      if (initialValues.level && !level) setLevel(initialValues.level);
    }
  }, [initialValues]);

  // LLM setup state
  const [selectedProvider, setSelectedProvider] =
    useState<ProviderKey>("anthropic");
  const [selectedModel, setSelectedModel] = useState<string>(
    PROVIDERS[0]?.models[0]?.name || ""
  );
  const [apiKey, setApiKey] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<
    "idle" | "testing" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = useState("");

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showSuccessPage, setShowSuccessPage] = useState(false);
  const autoCloseTriggered = useRef(false);

  const useLevelForPrompt = WORK_AREAS_WITH_LEVEL.includes(workArea);
  const isUserInfoValid = firstName.trim() && lastName.trim() && workArea;

  const currentProviderConfig = PROVIDERS.find(
    (p) => p.key === selectedProvider
  )!;
  const isLlmValid = apiKey.trim() && selectedModel;

  const totalSteps = showLlmSetup ? 2 : 1;
  const currentStepIndex = currentStep === "user-info" ? 0 : 1;

  // Auto-close after showing success page
  useEffect(() => {
    if (showSuccessPage && !autoCloseTriggered.current) {
      autoCloseTriggered.current = true;
      const timer = setTimeout(async () => {
        // Create the LLM provider
        if (showLlmSetup && apiKey.trim()) {
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

          const response = await fetch(
            `${LLM_PROVIDERS_ADMIN_URL}?is_creation=true`,
            {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            }
          );

          if (response.ok && (!llmProviders || llmProviders.length === 0)) {
            const newProvider = await response.json();
            if (newProvider?.id) {
              await fetch(
                `${LLM_PROVIDERS_ADMIN_URL}/${newProvider.id}/default`,
                {
                  method: "POST",
                }
              );
            }
          }

          // Refresh LLM providers list
          if (onLlmComplete) {
            await onLlmComplete();
          }
        }

        // Complete with user info
        await onComplete({
          firstName: firstName.trim(),
          lastName: lastName.trim(),
          workArea,
          level: useLevelForPrompt && level ? level : undefined,
        });
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [showSuccessPage]);

  const handleProviderChange = (provider: ProviderKey) => {
    setSelectedProvider(provider);
    const providerConfig = PROVIDERS.find((p) => p.key === provider)!;
    // Auto-select the first (recommended) model for this provider
    setSelectedModel(providerConfig.models[0]?.name || "");
    // Reset connection state
    setConnectionStatus("idle");
    setErrorMessage("");
  };

  const handleNext = () => {
    if (currentStep === "user-info" && showLlmSetup) {
      setCurrentStep("llm-setup");
    }
  };

  const handleBack = () => {
    if (currentStep === "llm-setup") {
      setCurrentStep("user-info");
    }
  };

  const handleTestConnection = async () => {
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

    setConnectionStatus("success");
    setShowSuccessPage(true);
  };

  const handleSubmit = async () => {
    if (!isUserInfoValid) return;
    if (showLlmSetup && connectionStatus !== "success") return;

    setIsSubmitting(true);

    try {
      // If LLM setup is required, create the provider first
      if (showLlmSetup && apiKey.trim()) {
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
            "There was an issue with this provider and model, please try a different one."
          );
          setConnectionStatus("error");
          setIsSubmitting(false);
          return;
        }

        // Set as default provider if it's the first one
        if (!llmProviders || llmProviders.length === 0) {
          const newProvider = await response.json();
          if (newProvider?.id) {
            await fetch(
              `${LLM_PROVIDERS_ADMIN_URL}/${newProvider.id}/default`,
              {
                method: "POST",
              }
            );
          }
        }
      }

      // Complete with user info
      await onComplete({
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        workArea,
        level: useLevelForPrompt && level ? level : undefined,
      });
    } catch (error) {
      setErrorMessage(
        "There was an issue with this provider and model, please try a different one."
      );
      setConnectionStatus("error");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!open) return null;

  const canProceedUserInfo = isUserInfoValid;
  const canTestConnection = isLlmValid && connectionStatus !== "testing";
  const canGetStarted = connectionStatus === "success";
  const isLastStep = !showLlmSetup || currentStep === "llm-setup";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6 min-h-[525px]">
          {/* User Info Step */}
          {currentStep === "user-info" && (
            <div className="flex-1 flex flex-col gap-6">
              {/* Header */}
              <div className="flex items-center justify-center gap-2">
                <Text headingH2 text05>
                  Tell us about yourself
                </Text>
                <SimpleTooltip
                  tooltip="We use this information to personalize your demo data and examples."
                  side="bottom"
                >
                  <button
                    type="button"
                    className="text-text-02 hover:text-text-03 transition-colors"
                  >
                    <SvgInfoSmall className="w-5 h-5" />
                  </button>
                </SimpleTooltip>
              </div>

              {/* Name inputs */}
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <Text secondaryBody text03>
                    First name
                  </Text>
                  <input
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="Steven"
                    className="w-full px-3 py-2 rounded-08 input-normal text-text-04 placeholder:text-text-02 focus:outline-none"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Text secondaryBody text03>
                    Last name
                  </Text>
                  <input
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    placeholder="Alexson"
                    className="w-full px-3 py-2 rounded-08 input-normal text-text-04 placeholder:text-text-02 focus:outline-none"
                  />
                </div>
              </div>

              {/* Work area */}
              <div className="flex flex-col gap-3 items-center">
                <Text mainUiBody text04>
                  What do you do?
                </Text>
                <div className="grid grid-cols-3 gap-3">
                  {WORK_AREA_OPTIONS.map((option) => (
                    <SelectableButton
                      key={option.value}
                      selected={workArea === option.value}
                      onClick={() =>
                        setWorkArea(
                          workArea === option.value ? "" : option.value
                        )
                      }
                    >
                      {option.label}
                    </SelectableButton>
                  ))}
                </div>
              </div>

              {/* Level */}
              <div className="flex flex-col gap-3 items-center">
                <Text mainUiBody text04>
                  Level
                </Text>
                <div className="flex justify-center gap-3">
                  {LEVEL_OPTIONS.map((option) => (
                    <SelectableButton
                      key={option.value}
                      selected={level === option.value}
                      onClick={() =>
                        setLevel(level === option.value ? "" : option.value)
                      }
                    >
                      {option.label}
                    </SelectableButton>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* LLM Setup Step - hide when showing success */}
          {currentStep === "llm-setup" && !showSuccessPage && (
            <div className="flex-1 flex flex-col gap-6">
              {/* Header */}
              <div className="flex items-center justify-center">
                <Text headingH2 text05>
                  Connect your LLM
                </Text>
              </div>

              {/* Provider selection */}
              <div className="flex flex-col gap-3 items-center">
                <Text mainUiBody text04>
                  Provider
                </Text>
                <div className="flex justify-center gap-3">
                  {PROVIDERS.map((provider) => (
                    <SelectableButton
                      key={provider.key}
                      selected={selectedProvider === provider.key}
                      onClick={() => handleProviderChange(provider.key)}
                      subtext={provider.recommended ? "Recommended" : undefined}
                      disabled={connectionStatus === "testing"}
                    >
                      {provider.label}
                    </SelectableButton>
                  ))}
                </div>
              </div>

              {/* Model selection */}
              <div className="flex flex-col gap-3 items-center">
                <Text mainUiBody text04>
                  Default Model
                </Text>
                <div className="flex justify-center gap-3 flex-wrap">
                  {currentProviderConfig.models.map((model) => (
                    <ModelSelectButton
                      key={model.name}
                      selected={selectedModel === model.name}
                      onClick={() => {
                        setSelectedModel(model.name);
                        setConnectionStatus("idle");
                        setErrorMessage("");
                      }}
                      label={model.label}
                      recommended={model.recommended}
                      disabled={connectionStatus === "testing"}
                    />
                  ))}
                </div>
              </div>

              {/* API Key input */}
              <div className="flex flex-col gap-1.5">
                <Text secondaryBody text03>
                  API Key
                </Text>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    setConnectionStatus("idle");
                    setErrorMessage("");
                  }}
                  placeholder={currentProviderConfig.apiKeyPlaceholder}
                  disabled={connectionStatus === "testing"}
                  className={cn(
                    "w-full px-3 py-2 rounded-08 input-normal text-text-04 placeholder:text-text-02 focus:outline-none",
                    connectionStatus === "testing" &&
                      "opacity-50 cursor-not-allowed"
                  )}
                />
                {connectionStatus === "error" && (
                  <Text secondaryBody className="text-red-500">
                    {errorMessage}
                  </Text>
                )}
              </div>
            </div>
          )}

          {/* Success Page */}
          {showSuccessPage && (
            <div className="flex-1 flex items-center justify-center">
              <div className="relative flex items-center justify-center">
                {/* Left accent marks */}
                <div className="absolute -left-16 flex flex-col gap-1">
                  <div className="w-8 h-1 bg-black dark:bg-white rounded-full" />
                  <div className="w-6 h-1 bg-black dark:bg-white rounded-full opacity-60" />
                  <div className="w-4 h-1 bg-black dark:bg-white rounded-full opacity-30" />
                </div>

                {/* Success text */}
                <Text headingH1 text05 className="text-4xl font-bold">
                  Success!
                </Text>

                {/* Right accent marks */}
                <div className="absolute -right-16 flex flex-col gap-1 items-end">
                  <div className="w-8 h-1 bg-black dark:bg-white rounded-full" />
                  <div className="w-6 h-1 bg-black dark:bg-white rounded-full opacity-60" />
                  <div className="w-4 h-1 bg-black dark:bg-white rounded-full opacity-30" />
                </div>
              </div>
            </div>
          )}

          {/* Navigation buttons - hide on success page */}
          {!showSuccessPage && (
            <div className="relative flex justify-between items-center pt-2">
              {/* Back button */}
              <div>
                {currentStep !== "user-info" && (
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

              {/* Step indicator - absolutely centered */}
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
                  onClick={isLastStep ? handleSubmit : handleNext}
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
                    {isLastStep ? "Get Started!" : "Continue"}
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

              {currentStep === "llm-setup" &&
                connectionStatus !== "success" && (
                  <button
                    type="button"
                    onClick={handleTestConnection}
                    disabled={!canTestConnection}
                    className={cn(
                      "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                      canTestConnection
                        ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                        : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
                    )}
                  >
                    <Text
                      mainUiAction
                      className={cn(
                        canTestConnection
                          ? "text-white dark:text-black"
                          : "text-text-02"
                      )}
                    >
                      {connectionStatus === "testing"
                        ? "Testing..."
                        : "Test Connection"}
                    </Text>
                  </button>
                )}

              {currentStep === "llm-setup" &&
                connectionStatus === "success" && (
                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={isSubmitting}
                    className={cn(
                      "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                      !isSubmitting
                        ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                        : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
                    )}
                  >
                    <Text
                      mainUiAction
                      className={cn(
                        !isSubmitting
                          ? "text-white dark:text-black"
                          : "text-text-02"
                      )}
                    >
                      {isSubmitting ? "Saving..." : "Get Started!"}
                    </Text>
                  </button>
                )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
