"use client";

import { useState, useEffect, useMemo } from "react";
import { SvgArrowRight, SvgArrowLeft, SvgCheckCircle } from "@opal/icons";
import { FiInfo } from "react-icons/fi";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  BuildUserInfo,
  OnboardingModalMode,
  OnboardingStep,
} from "@/app/build/onboarding/types";
import {
  WORK_AREA_OPTIONS,
  LEVEL_OPTIONS,
  WORK_AREAS_WITH_LEVEL,
  setBuildLlmSelection,
  getBuildLlmSelection,
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
import {
  GoogleDriveIcon,
  GithubIcon,
  HubSpotIcon,
  LinearIcon,
  FirefliesIcon,
} from "@/components/icons/icons";

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

// Priority order for auto-selecting LLM when user completes onboarding without explicit selection
const LLM_AUTO_SELECT_PRIORITY = [
  { provider: "anthropic", model: "claude-opus-4-5" },
  { provider: "openai", model: "gpt-5.2" },
  { provider: "anthropic", model: "claude-sonnet-4-5" },
  { provider: "openai", model: "gpt-5.1-codex" },
  { provider: "openrouter", model: "moonshotai/kimi-k2-thinking" },
] as const;

/**
 * Auto-select the best available LLM based on priority order.
 * Used when user completes onboarding without going through LLM setup step.
 */
function autoSelectBestLlm(
  llmProviders: LLMProviderDescriptor[] | undefined
): void {
  // Don't override if user already has a selection
  if (getBuildLlmSelection()) return;

  if (!llmProviders || llmProviders.length === 0) return;

  // Try each priority option in order
  for (const { provider, model } of LLM_AUTO_SELECT_PRIORITY) {
    const matchingProvider = llmProviders.find((p) => p.provider === provider);
    if (matchingProvider) {
      // Check if the preferred model is available
      const hasModel = matchingProvider.model_configurations.some(
        (m) => m.name === model
      );
      if (hasModel) {
        setBuildLlmSelection({
          providerName: matchingProvider.name,
          provider: matchingProvider.provider,
          modelName: model,
        });
        return;
      }
    }
  }

  // Fallback: use the default provider's default model
  const defaultProvider = llmProviders.find((p) => p.is_default_provider);
  if (defaultProvider) {
    setBuildLlmSelection({
      providerName: defaultProvider.name,
      provider: defaultProvider.provider,
      modelName: defaultProvider.default_model_name,
    });
  }
}

interface SelectableButtonProps {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  subtext?: string;
  disabled?: boolean;
  tooltip?: string;
}

function SelectableButton({
  selected,
  onClick,
  children,
  subtext,
  disabled,
  tooltip,
}: SelectableButtonProps) {
  const button = (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "w-full px-6 py-3 rounded-12 border transition-colors",
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

  if (tooltip) {
    return <SimpleTooltip tooltip={tooltip}>{button}</SimpleTooltip>;
  }

  return button;
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
    <div className="flex flex-col items-center gap-1 w-full">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "w-full px-4 py-2.5 rounded-12 border transition-colors",
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
      // Full flow: user-info (if needed) → llm-setup (if admin + not all configured) → page1 → page2
      const steps: OnboardingStep[] = [];
      if (!hasUserInfo) {
        steps.push("user-info");
      }
      if (isAdmin && !allProvidersConfigured) {
        steps.push("llm-setup");
      }
      steps.push("page1", "page2");
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
      const providerConfig = PROVIDERS.find((p) => p.key === mode.provider);
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

  const useLevelForPrompt = WORK_AREAS_WITH_LEVEL.includes(workArea);
  const isUserInfoValid = firstName.trim() && lastName.trim() && workArea;

  const currentProviderConfig = PROVIDERS.find(
    (p) => p.key === selectedProvider
  )!;
  const isLlmValid = apiKey.trim() && selectedModel;

  // Check if a provider is already configured
  const isProviderConfigured = (providerName: string) => {
    return llmProviders?.some((p) => p.provider === providerName) ?? false;
  };

  // Calculate step navigation
  const currentStepIndex = steps.indexOf(currentStep);
  const totalSteps = steps.length;

  const handleProviderChange = (provider: ProviderKey) => {
    const providerConfig = PROVIDERS.find((p) => p.key === provider)!;
    // Don't allow selecting already-configured providers
    if (isProviderConfigured(providerConfig.providerName)) return;

    setSelectedProvider(provider);
    setSelectedModel(providerConfig.models[0]?.name || "");
    setConnectionStatus("idle");
    setErrorMessage("");
  };

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

      await onComplete({
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        workArea,
        level: useLevelForPrompt && level ? level : undefined,
      });

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

  // Handle final step action based on mode
  const handleFinalAction = () => {
    if (currentStep === steps[steps.length - 1]) {
      handleSubmit();
    } else {
      handleNext();
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
        <div className="p-6 flex flex-col gap-6 min-h-[600px]">
          {/* User Info Step */}
          {currentStep === "user-info" && (
            <div className="flex-1 flex flex-col gap-6">
              {/* Header */}
              <div className="flex items-center justify-center gap-2">
                <SimpleTooltip
                  tooltip="We use this information to personalize your demo data and examples."
                  side="bottom"
                >
                  <button
                    type="button"
                    className="text-text-02 hover:text-text-03 transition-colors"
                  >
                    <FiInfo size={16} className="text-text-03" />
                  </button>
                </SimpleTooltip>
                <Text headingH2 text05>
                  Tell us about yourself
                </Text>
              </div>

              <div className="flex-1 flex flex-col gap-8 justify-center">
                {/* Name inputs */}
                <div className="flex justify-center">
                  <div className="grid grid-cols-2 gap-4 w-full max-w-md">
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
                </div>

                {/* Work area */}
                <div className="flex flex-col gap-3 items-center">
                  <Text mainUiBody text04>
                    What do you do?
                  </Text>
                  <div className="grid grid-cols-3 gap-3 w-full">
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
                  <div className="flex justify-center gap-3 w-full">
                    <div className="grid grid-cols-2 gap-3 w-2/3">
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
              </div>
            </div>
          )}

          {/* LLM Setup Step */}
          {currentStep === "llm-setup" && (
            <div className="flex-1 flex flex-col gap-6 justify-between">
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
                <div className="flex justify-center gap-3 w-full max-w-md">
                  {PROVIDERS.map((provider) => {
                    const isConfigured = isProviderConfigured(
                      provider.providerName
                    );
                    return (
                      <div key={provider.key} className="flex-1">
                        <SelectableButton
                          selected={selectedProvider === provider.key}
                          onClick={() => handleProviderChange(provider.key)}
                          subtext={
                            isConfigured
                              ? "Already configured"
                              : provider.recommended
                                ? "Recommended"
                                : undefined
                          }
                          disabled={
                            connectionStatus === "testing" || isConfigured
                          }
                          tooltip={
                            isConfigured
                              ? "This provider is already configured"
                              : undefined
                          }
                        >
                          {provider.label}
                        </SelectableButton>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Model selection */}
              <div className="flex flex-col gap-3 items-center">
                <Text mainUiBody text04>
                  Default Model
                </Text>
                <div className="flex justify-center gap-3 flex-wrap w-full max-w-md">
                  {currentProviderConfig.models.map((model) => (
                    <div key={model.name} className="flex-1 min-w-0">
                      <ModelSelectButton
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
                    </div>
                  ))}
                </div>
              </div>

              {/* API Key input */}
              <div className="flex flex-col gap-3 items-center">
                <Text mainUiBody text04>
                  API Key
                </Text>
                <div className="w-full max-w-md">
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
                  {/* Message area */}
                  <div className="min-h-[2rem] flex justify-center pt-4">
                    {connectionStatus === "error" && (
                      <Text secondaryBody className="text-red-500">
                        {errorMessage}
                      </Text>
                    )}
                    <div
                      className={cn(
                        "flex items-center gap-2 px-3 py-2 rounded-08 bg-status-success-00 border border-status-success-02 w-fit",
                        connectionStatus !== "success" && "hidden"
                      )}
                    >
                      <SvgCheckCircle className="w-4 h-4 stroke-status-success-05 shrink-0" />
                      <Text secondaryBody className="text-status-success-05">
                        Success!
                      </Text>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Page 1 - What is Onyx Craft? */}
          {currentStep === "page1" && (
            <div className="flex-1 flex flex-col gap-6 items-center justify-center">
              <Text headingH2 text05>
                What is Onyx Craft?
              </Text>
              <img
                src="/craft_demo_image_1.png"
                alt="Onyx Craft"
                className="max-w-full h-auto rounded-12"
              />
              <Text mainContentBody text04 className="text-center">
                Beautiful dashboards, slides, and reports.
                <br />
                Built by AI agents that know your world. Privately and securely.
              </Text>
            </div>
          )}

          {/* Page 2 - Let's get started */}
          {currentStep === "page2" && (
            <div className="flex-1 flex flex-col gap-6 items-center justify-center">
              <Text headingH2 text05>
                Let's get started!
              </Text>
              <img
                src="/craft_demo_image_2.png"
                alt="Onyx Craft"
                className="max-w-full h-auto rounded-12"
              />
              <Text mainContentBody text04 className="text-center">
                While we sync your data, try our demo dataset
                <br />
                of 1,000+ simulated documents across 5 apps!
                <br />
              </Text>
              <div className="flex items-center justify-center gap-4">
                <SimpleTooltip tooltip="Google Drive">
                  <span className="inline-flex items-center cursor-help">
                    <GoogleDriveIcon size={25} />
                  </span>
                </SimpleTooltip>
                <SimpleTooltip tooltip="GitHub">
                  <span className="inline-flex items-center cursor-help">
                    <GithubIcon size={25} />
                  </span>
                </SimpleTooltip>
                <SimpleTooltip tooltip="HubSpot">
                  <span className="inline-flex items-center cursor-help">
                    <HubSpotIcon size={25} />
                  </span>
                </SimpleTooltip>
                <SimpleTooltip tooltip="Linear">
                  <span className="inline-flex items-center cursor-help">
                    <LinearIcon size={25} />
                  </span>
                </SimpleTooltip>
                <SimpleTooltip tooltip="Fireflies">
                  <span className="inline-flex items-center cursor-help">
                    <FirefliesIcon size={25} />
                  </span>
                </SimpleTooltip>
              </div>
            </div>
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
                  {isLastStep
                    ? isSubmitting
                      ? "Saving..."
                      : "Save"
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
                className="flex items-center gap-1.5 px-4 py-2 rounded-12 bg-black dark:bg-white text-white dark:text-black hover:opacity-90 transition-colors"
              >
                <Text mainUiAction className="text-white dark:text-black">
                  Continue
                </Text>
                <SvgArrowRight className="w-4 h-4 text-white dark:text-black" />
              </button>
            )}

            {currentStep === "page2" && (
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
