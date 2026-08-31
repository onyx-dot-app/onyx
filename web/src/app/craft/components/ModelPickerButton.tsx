"use client";

import { useMemo } from "react";
import { SelectButton } from "@opal/components";
import { cn } from "@opal/utils";
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
  // Whether a pick should also be remembered as the user's personal choice.
  // Admin contexts editing a workspace-wide setting pass `false`.
  persistSelection?: boolean;
  // Set while the caller is still resolving `selection`. The picker also
  // detects its own provider fetch, so callers only need this when their
  // selection comes from a separate request.
  loading?: boolean;
}

// Figure spaces: give the loading pill a model-name-ish width without a fixed
// size, so the label swap doesn't shift the row.
const SKELETON_LABEL = "\u2007".repeat(10);

// Controlled model picker pill matching the main app's ModelSelector.
export default function ModelPickerButton({
  selection,
  onChange,
  disabled = false,
  fallbackToDefault = true,
  placeholder = "Select model",
  persistSelection = true,
  loading = false,
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

  // A placeholder here would read as "unset" while the value is merely
  // unknown, so hold a blank label until the providers land. The button stays
  // enabled — `select-input` goes transparent when disabled, and losing the
  // box mid-load is worse than a popover that opens a beat early.
  const isResolving = loading || !llmProviders;

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
      persistSelection={persistSelection}
    >
      <div
        className={cn(
          "inline-flex",
          isResolving && "motion-safe:animate-pulse"
        )}
        aria-busy={isResolving}
      >
        <SelectButton
          icon={isResolving ? undefined : ModelIcon}
          state="empty"
          variant="select-input"
          size="lg"
          disabled={disabled}
        >
          {isResolving ? SKELETON_LABEL : displayName}
        </SelectButton>
      </div>
    </BuildLLMPopover>
  );
}
