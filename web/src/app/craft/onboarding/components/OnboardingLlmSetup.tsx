"use client";

import { SvgCheckCircle } from "@opal/icons";
import { cn } from "@/lib/utils";
import { Disabled } from "@/refresh-components/Disabled";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  LLMProviderName,
  LLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";

// Provider configurations
export type ProviderKey = "anthropic" | "openai" | "openrouter";

interface ModelOption {
  name: string;
  label: string;
  recommended?: boolean;
}

export interface ProviderConfig {
  key: ProviderKey;
  label: string;
  providerName: LLMProviderName;
  recommended?: boolean;
  models: ModelOption[];
  apiKeyPlaceholder: string;
  apiKeyUrl: string;
  apiKeyLabel: string;
}

export const PROVIDERS: ProviderConfig[] = [
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
      <Disabled disabled={disabled} allowClick>
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          className={cn(
            "w-full px-6 py-3 rounded-12 border transition-colors",
            selected
              ? "border-action-link-05 bg-action-link-01 text-action-text-link-05"
              : "border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-01"
          )}
        >
          <Text mainUiAction>{children}</Text>
        </button>
      </Disabled>
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
      <Disabled disabled={disabled} allowClick>
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          className={cn(
            "w-full px-4 py-2.5 rounded-12 border transition-colors",
            selected
              ? "border-action-link-05 bg-action-link-01 text-action-text-link-05"
              : "border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-01"
          )}
        >
          <Text mainUiAction>{label}</Text>
        </button>
      </Disabled>
      {recommended && (
        <Text figureSmallLabel text02>
          Recommended
        </Text>
      )}
    </div>
  );
}

interface OnboardingLlmSetupProps {
  selectedProvider: ProviderKey;
  selectedModel: string;
  apiKey: string;
  connectionStatus: "idle" | "testing" | "success" | "error";
  errorMessage: string;
  llmProviders?: LLMProviderDescriptor[];
  onProviderChange: (provider: ProviderKey) => void;
  onModelChange: (model: string) => void;
  onApiKeyChange: (apiKey: string) => void;
  onConnectionStatusChange: (
    status: "idle" | "testing" | "success" | "error"
  ) => void;
  onErrorMessageChange: (message: string) => void;
}

export default function OnboardingLlmSetup({
  selectedProvider,
  selectedModel,
  apiKey,
  connectionStatus,
  errorMessage,
  llmProviders,
  onProviderChange,
  onModelChange,
  onApiKeyChange,
  onConnectionStatusChange,
  onErrorMessageChange,
}: OnboardingLlmSetupProps) {
  const currentProviderConfig = PROVIDERS.find(
    (p) => p.key === selectedProvider
  )!;

  const isProviderConfigured = (providerName: string) => {
    return llmProviders?.some((p) => p.provider === providerName) ?? false;
  };

  const handleProviderChange = (provider: ProviderKey) => {
    const providerConfig = PROVIDERS.find((p) => p.key === provider)!;
    // Don't allow selecting already-configured providers
    if (isProviderConfigured(providerConfig.providerName)) return;

    onProviderChange(provider);
    onModelChange(providerConfig.models[0]?.name || "");
    onConnectionStatusChange("idle");
    onErrorMessageChange("");
  };

  const handleModelChange = (model: string) => {
    onModelChange(model);
    onConnectionStatusChange("idle");
    onErrorMessageChange("");
  };

  const handleApiKeyChange = (value: string) => {
    onApiKeyChange(value);
    onConnectionStatusChange("idle");
    onErrorMessageChange("");
  };

  return (
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
            const isConfigured = isProviderConfigured(provider.providerName);
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
                  disabled={connectionStatus === "testing" || isConfigured}
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
                onClick={() => handleModelChange(model.name)}
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
          <Disabled disabled={connectionStatus === "testing"} allowClick>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => handleApiKeyChange(e.target.value)}
              placeholder={currentProviderConfig.apiKeyPlaceholder}
              disabled={connectionStatus === "testing"}
              className="w-full px-3 py-2 rounded-08 input-normal text-text-04 placeholder:text-text-02 focus:outline-none"
            />
          </Disabled>
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
  );
}
