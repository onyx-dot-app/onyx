"use client";

import { useMemo } from "react";
import { SelectButton } from "@opal/components";
import { BuildLLMPopover } from "@/app/craft/components/BuildLLMPopover";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { getModelIcon } from "@/lib/languageModels";
import { BuildLlmSelection } from "@/app/craft/onboarding/constants";
import { getPreferredLlmSelection } from "@/app/craft/utils/llmPreferences";
import { useUser } from "@/providers/UserProvider";

interface ModelPickerButtonProps {
  // null → show the recommended default (or `placeholder`, if `fallbackToDefault` is false).
  selection: BuildLlmSelection | null;
  onChange: (selection: BuildLlmSelection) => void;
  disabled?: boolean;
  // Whether a null `selection` should fall back to the user's remembered
  // pick / workspace default. Admin contexts that display a workspace-wide
  // setting should pass `false` so the admin's own personal pick can't leak
  // in as if it were the setting's value.
  fallbackToDefault?: boolean;
  // Label shown when there is no selection and `fallbackToDefault` is false.
  placeholder?: string;
}

// Controlled model picker pill matching the main app's ModelSelector.
export default function ModelPickerButton({
  selection,
  onChange,
  disabled = false,
  fallbackToDefault = true,
  placeholder = "Select model",
}: ModelPickerButtonProps) {
  const { llmProviders, defaultText, defaultCraft } = useLLMProviders();
  const { user } = useUser();

  const effective = useMemo(
    () =>
      selection ??
      (fallbackToDefault
        ? getPreferredLlmSelection(user?.id, llmProviders, [
            defaultCraft,
            defaultText,
          ])
        : null),
    [
      selection,
      fallbackToDefault,
      user?.id,
      llmProviders,
      defaultCraft,
      defaultText,
    ]
  );

  const displayName = useMemo(() => {
    if (!effective) return placeholder;
    const provider = llmProviders?.find(
      (candidate) => candidate.id === effective.providerId
    );
    const config = provider?.model_configurations.find(
      (model) => model.name === effective.modelName
    );
    if (config) return config.effectiveDisplayName;
    return effective.modelName;
  }, [effective, llmProviders, placeholder]);

  const ModelIcon = effective
    ? getModelIcon(effective.provider, effective.modelName)
    : undefined;

  return (
    <BuildLLMPopover
      currentSelection={effective}
      onSelectionChange={onChange}
      llmProviders={llmProviders}
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
