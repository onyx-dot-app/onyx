"use client";

import { useMemo } from "react";
import { SelectButton } from "@opal/components";
import { BuildLLMPopover } from "@/app/craft/components/BuildLLMPopover";
import { useOnboarding } from "@/app/craft/onboarding/BuildOnboardingProvider";
import { useLLMProviders } from "@/hooks/useLanguageModels";
import { getModelIcon } from "@/lib/languageModels";
import {
  BuildLlmSelection,
  BUILD_MODE_PROVIDERS,
  getDefaultLlmSelection,
} from "@/app/craft/onboarding/constants";

interface ModelPickerButtonProps {
  // null → show the recommended default.
  selection: BuildLlmSelection | null;
  onChange: (selection: BuildLlmSelection) => void;
  disabled?: boolean;
}

// Controlled model picker pill matching the main app's ModelSelector.
export default function ModelPickerButton({
  selection,
  onChange,
  disabled = false,
}: ModelPickerButtonProps) {
  const { llmProviders } = useLLMProviders();
  const { openLlmSetup } = useOnboarding();

  const effective = useMemo(
    () => selection ?? getDefaultLlmSelection(llmProviders),
    [selection, llmProviders]
  );

  const displayName = useMemo(() => {
    if (!effective) return "Select model";
    if (llmProviders) {
      for (const provider of llmProviders) {
        const config = provider.model_configurations.find(
          (m) => m.name === effective.modelName
        );
        if (config) return config.display_name || config.name;
      }
    }
    for (const provider of BUILD_MODE_PROVIDERS) {
      const model = provider.models.find((m) => m.name === effective.modelName);
      if (model) return model.label;
    }
    return effective.modelName;
  }, [effective, llmProviders]);

  const ModelIcon = effective ? getModelIcon(effective.provider) : undefined;

  return (
    <BuildLLMPopover
      currentSelection={effective}
      onSelectionChange={onChange}
      llmProviders={llmProviders}
      onOpenOnboarding={(providerKey) => openLlmSetup(providerKey)}
      disabled={disabled}
    >
      <div className="inline-flex">
        <SelectButton
          icon={ModelIcon}
          state="empty"
          variant="select-input"
          size="lg"
          disabled={disabled}
        >
          {displayName}
        </SelectButton>
      </div>
    </BuildLLMPopover>
  );
}
