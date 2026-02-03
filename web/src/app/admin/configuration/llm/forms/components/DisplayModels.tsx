import { ModelConfiguration, SimpleKnownModel } from "../../interfaces";
import { FormikProps } from "formik";
import { BaseLLMFormValues } from "../formUtils";
import { useMemo } from "react";

import Checkbox from "@/refresh-components/inputs/Checkbox";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { FieldLabel } from "@/components/Field";

interface AutoModeToggleProps {
  isAutoMode: boolean;
  onToggle: () => void;
}

function AutoModeToggle({ isAutoMode, onToggle }: AutoModeToggleProps) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <Text as="p" mainUiAction className="block">
          Auto Update
        </Text>
        <Text as="p" secondaryBody text03 className="block">
          Automatically update the available models when new models are
          released. Recommended for most teams.
        </Text>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={isAutoMode}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full",
          "border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none",
          isAutoMode ? "bg-action-link-05" : "bg-background-neutral-03"
        )}
        onClick={onToggle}
      >
        <span
          className={cn(
            "pointer-events-none inline-block h-5 w-5 transform rounded-full",
            "bg-white shadow ring-0 transition duration-200 ease-in-out",
            isAutoMode ? "translate-x-5" : "translate-x-0"
          )}
        />
      </button>
    </div>
  );
}

function DisplayModelHeader({ alternativeText }: { alternativeText?: string }) {
  return (
    <div>
      <FieldLabel
        label="Available Models"
        subtext={
          alternativeText ??
          "Select which models to make available for this provider."
        }
        name="_available-models"
      />
    </div>
  );
}

export function DisplayModels<T extends BaseLLMFormValues>({
  formikProps,
  modelConfigurations,
  noModelConfigurationsMessage,
  isLoading,
  recommendedDefaultModel,
  shouldShowAutoUpdateToggle,
}: {
  formikProps: FormikProps<T>;
  modelConfigurations: ModelConfiguration[];
  noModelConfigurationsMessage?: string;
  isLoading?: boolean;
  recommendedDefaultModel: SimpleKnownModel | null;
  shouldShowAutoUpdateToggle: boolean;
}) {
  const isAutoMode = formikProps.values.is_auto_mode;

  if (isLoading) {
    return (
      <div>
        <DisplayModelHeader />
        <div className="mt-2 flex items-center p-3 border border-border-01 rounded-lg bg-background-neutral-00">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-border-03 border-t-action-link-05" />
        </div>
      </div>
    );
  }

  const handleCheckboxChange = (modelName: string, checked: boolean) => {
    // Read current values inside the handler to avoid stale closure issues
    const currentSelected = formikProps.values.selected_model_names ?? [];
    const currentDefault = formikProps.values.default_model_name;

    if (checked) {
      const newSelected = [...currentSelected, modelName];
      formikProps.setFieldValue("selected_model_names", newSelected);
      // If this is the first model, set it as default
      if (currentSelected.length === 0) {
        formikProps.setFieldValue("default_model_name", modelName);
      }
    } else {
      const newSelected = currentSelected.filter((name) => name !== modelName);
      formikProps.setFieldValue("selected_model_names", newSelected);
      // If removing the default, set the first remaining model as default
      if (currentDefault === modelName && newSelected.length > 0) {
        formikProps.setFieldValue("default_model_name", newSelected[0]);
      } else if (newSelected.length === 0) {
        formikProps.setFieldValue("default_model_name", null);
      }
    }
  };

  const handleSetDefault = (modelName: string) => {
    formikProps.setFieldValue("default_model_name", modelName);
  };

  const handleToggleAutoMode = () => {
    formikProps.setFieldValue("is_auto_mode", !isAutoMode);
    formikProps.setFieldValue(
      "selected_model_names",
      modelConfigurations.filter((m) => m.is_visible).map((m) => m.name)
    );
    formikProps.setFieldValue(
      "default_model_name",
      recommendedDefaultModel?.name ?? ""
    );
  };

  const selectedModels = formikProps.values.selected_model_names ?? [];
  const defaultModel = formikProps.values.default_model_name;
  const selectedModelSet = useMemo(
    () => new Set(selectedModels),
    [selectedModels]
  );
  const allModelNames = useMemo(
    () => modelConfigurations.map((model) => model.name),
    [modelConfigurations]
  );
  const areAllModelsSelected =
    allModelNames.length > 0 &&
    allModelNames.every((modelName) => selectedModelSet.has(modelName));
  const areSomeModelsSelected = selectedModels.length > 0;

  const handleSelectAllModels = () => {
    formikProps.setFieldValue("selected_model_names", allModelNames);

    const currentDefault = defaultModel ?? "";
    const hasValidDefault =
      currentDefault.length > 0 && allModelNames.includes(currentDefault);

    if (!hasValidDefault && allModelNames.length > 0) {
      const nextDefault =
        recommendedDefaultModel &&
        allModelNames.includes(recommendedDefaultModel.name)
          ? recommendedDefaultModel.name
          : allModelNames[0];
      formikProps.setFieldValue("default_model_name", nextDefault ?? null);
    }
  };
  const handleClearAllModels = () => {
    formikProps.setFieldValue("selected_model_names", []);
    formikProps.setFieldValue("default_model_name", null);
  };

  if (modelConfigurations.length === 0) {
    return (
      <div>
        <DisplayModelHeader
          alternativeText={noModelConfigurationsMessage ?? "No models found"}
        />
      </div>
    );
  }

  // Sort auto mode models: default model first
  const visibleModels = modelConfigurations.filter((m) => m.is_visible);
  const sortedAutoModels = [...visibleModels].sort((a, b) => {
    const aIsDefault = a.name === defaultModel;
    const bIsDefault = b.name === defaultModel;
    if (aIsDefault && !bIsDefault) return -1;
    if (!aIsDefault && bIsDefault) return 1;
    return 0;
  });

  return (
    <div className="flex flex-col gap-3">
      <DisplayModelHeader />
      {!isAutoMode && modelConfigurations.length > 0 && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Checkbox
              checked={areAllModelsSelected}
              indeterminate={areSomeModelsSelected && !areAllModelsSelected}
              onCheckedChange={(checked) =>
                checked ? handleSelectAllModels() : handleClearAllModels()
              }
              aria-label="Select all models"
            />
            <button
              type="button"
              className={cn(
                "text-xs font-medium text-text-03 hover:text-text-05",
                !areSomeModelsSelected && "text-text-02 hover:text-text-02"
              )}
              onClick={() =>
                areAllModelsSelected
                  ? handleClearAllModels()
                  : handleSelectAllModels()
              }
            >
              Select all models
            </button>
          </div>
          {areSomeModelsSelected && (
            <button
              type="button"
              className="text-xs font-medium text-action-link-05 hover:text-action-link-06"
              onClick={handleClearAllModels}
            >
              Clear all ({selectedModels.length})
            </button>
          )}
        </div>
      )}
      <div className="border border-border-01 rounded-lg p-3">
        {shouldShowAutoUpdateToggle && (
          <AutoModeToggle
            isAutoMode={isAutoMode}
            onToggle={handleToggleAutoMode}
          />
        )}

        {/* Model list section */}
        <div
          className={cn(
            "flex flex-col gap-1",
            shouldShowAutoUpdateToggle && "mt-3 pt-3 border-t border-border-01"
          )}
        >
          {isAutoMode && shouldShowAutoUpdateToggle ? (
            // Auto mode: read-only display
            <div className="flex flex-col gap-2">
              {sortedAutoModels.map((model) => {
                const isDefault = model.name === defaultModel;
                return (
                  <div
                    key={model.name}
                    className={cn(
                      "flex items-center justify-between gap-3 rounded-lg border p-1",
                      "bg-background-neutral-00",
                      isDefault ? "border-action-link-05" : "border-border-01"
                    )}
                  >
                    <div className="flex flex-1 items-center gap-2 px-2 py-1">
                      <div
                        className={cn(
                          "size-2 shrink-0 rounded-full",
                          isDefault
                            ? "bg-action-link-05"
                            : "bg-background-neutral-03"
                        )}
                      />
                      <div className="flex flex-col gap-0.5">
                        <Text mainUiAction text05>
                          {model.display_name || model.name}
                        </Text>
                        {model.display_name && (
                          <Text secondaryBody text03>
                            {model.name}
                          </Text>
                        )}
                      </div>
                    </div>
                    {isDefault && (
                      <div className="flex items-center justify-end pr-2">
                        <Text
                          secondaryBody
                          className="text-action-text-link-05"
                        >
                          Default
                        </Text>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            // Manual mode: checkbox selection
            <div
              className={cn(
                "flex flex-col gap-1",
                "max-h-48 4xl:max-h-64",
                "overflow-y-auto"
              )}
            >
              {modelConfigurations.map((modelConfiguration) => {
                const isSelected = selectedModels.includes(
                  modelConfiguration.name
                );
                const isDefault = defaultModel === modelConfiguration.name;

                return (
                  <div
                    key={modelConfiguration.name}
                    className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-background-neutral-subtle"
                  >
                    <div
                      className="flex items-center gap-2 cursor-pointer"
                      onClick={() =>
                        handleCheckboxChange(
                          modelConfiguration.name,
                          !isSelected
                        )
                      }
                    >
                      <div
                        className="flex items-center"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Checkbox
                          checked={isSelected}
                          onCheckedChange={(checked) =>
                            handleCheckboxChange(
                              modelConfiguration.name,
                              checked
                            )
                          }
                        />
                      </div>
                      <Text
                        as="p"
                        secondaryBody
                        className="select-none leading-none"
                      >
                        {modelConfiguration.name}
                      </Text>
                    </div>
                    <button
                      type="button"
                      disabled={!isSelected}
                      onClick={() => handleSetDefault(modelConfiguration.name)}
                      className={`text-xs px-2 py-0.5 rounded transition-all duration-200 ease-in-out ${
                        isSelected
                          ? "opacity-100 translate-x-0"
                          : "opacity-0 translate-x-2 pointer-events-none"
                      } ${
                        isDefault
                          ? "bg-action-link-05 text-text-inverse font-medium scale-100"
                          : "bg-background-neutral-02 text-text-03 hover:bg-background-neutral-03 scale-95 hover:scale-100"
                      }`}
                    >
                      {isDefault ? "Default" : "Set as default"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
