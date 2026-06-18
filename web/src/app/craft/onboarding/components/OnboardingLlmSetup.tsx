"use client";

import { SvgCheckCircle } from "@opal/icons";
import { cn } from "@opal/utils";
import { Disabled } from "@opal/core";
import { Text, Tooltip } from "@opal/components";
import { LLMProviderDescriptor } from "@/lib/languageModels/types";
import {
  CRAFT_PROVIDERS,
  craftModelName,
  type ProviderKey,
} from "@/app/craft/onboarding/constants";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";
import { getProvider } from "@/lib/languageModels";

export type { ProviderKey };

interface SelectableButtonProps {
  selected: boolean;
  onClick: () => void;
  children: string;
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
          <Text font="main-ui-action" color="text-05">
            {children}
          </Text>
        </button>
      </Disabled>
      {subtext && (
        <Text font="figure-small-label" color="text-02">
          {subtext}
        </Text>
      )}
    </div>
  );

  if (tooltip) {
    return <Tooltip tooltip={tooltip}>{button}</Tooltip>;
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
          <Text font="main-ui-action" color="text-05">
            {label}
          </Text>
        </button>
      </Disabled>
      {recommended && (
        <Text font="figure-small-label" color="text-02">
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
  const { llmProviderOptions } = useLLMProviderOptions();

  const knownModelsFor = (providerType: string) =>
    llmProviderOptions?.find((o) => o.name === providerType)?.known_models ??
    [];
  // Recommended default first; stable sort keeps the rest in provider order.
  const currentModels = knownModelsFor(selectedProvider)
    .filter((m) => m.is_visible)
    .sort(
      (a, b) =>
        Number(b.is_recommended_default) - Number(a.is_recommended_default)
    );

  const isProviderConfigured = (providerType: string) => {
    return llmProviders?.some((p) => p.provider === providerType) ?? false;
  };

  const handleProviderChange = (provider: ProviderKey) => {
    // Don't allow selecting already-configured providers
    if (isProviderConfigured(provider)) return;

    onProviderChange(provider);
    onModelChange(craftModelName(knownModelsFor(provider)) ?? "");
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
        <Text font="heading-h2" color="text-05">
          Connect your LLM
        </Text>
      </div>

      {/* Provider selection */}
      <div className="flex flex-col gap-3 items-center">
        <Text font="main-ui-body" color="text-04">
          Provider
        </Text>
        <div className="flex justify-center gap-3 w-full max-w-md">
          {CRAFT_PROVIDERS.map(({ key, recommended }) => {
            const isConfigured = isProviderConfigured(key);
            return (
              <div key={key} className="flex-1">
                <SelectableButton
                  selected={selectedProvider === key}
                  onClick={() => handleProviderChange(key)}
                  subtext={
                    isConfigured
                      ? "Already configured"
                      : recommended
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
                  {getProvider(key).companyName}
                </SelectableButton>
              </div>
            );
          })}
        </div>
      </div>

      {/* Model selection */}
      <div className="flex flex-col gap-3 items-center">
        <Text font="main-ui-body" color="text-04">
          Default Model
        </Text>
        <div className="flex justify-center gap-3 flex-wrap w-full max-w-md">
          {currentModels.map((model) => (
            <div key={model.name} className="flex-1 min-w-0">
              <ModelSelectButton
                selected={selectedModel === model.name}
                onClick={() => handleModelChange(model.name)}
                label={model.display_name || model.name}
                recommended={model.is_recommended_default}
                disabled={connectionStatus === "testing"}
              />
            </div>
          ))}
        </div>
      </div>

      {/* API Key input */}
      <div className="flex flex-col gap-3 items-center">
        <Text font="main-ui-body" color="text-04">
          API Key
        </Text>
        <div className="w-full max-w-md">
          <Disabled disabled={connectionStatus === "testing"} allowClick>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => handleApiKeyChange(e.target.value)}
              placeholder={
                CRAFT_PROVIDERS.find((p) => p.key === selectedProvider)
                  ?.apiKeyPlaceholder
              }
              disabled={connectionStatus === "testing"}
              className="w-full px-3 py-2 rounded-08 input-normal text-text-04 placeholder:text-text-02 focus:outline-hidden"
            />
          </Disabled>
          {/* Message area */}
          <div className="min-h-8 flex justify-center pt-4">
            {connectionStatus === "error" && (
              <Text font="secondary-body" color="status-error-05">
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
              <Text font="secondary-body" color="status-success-05">
                Success!
              </Text>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
