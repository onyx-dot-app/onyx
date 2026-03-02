import { ModelConfiguration, SimpleKnownModel } from "@/interfaces/llm";
import { FormikProps } from "formik";
import { BaseLLMFormValues } from "../formUtils";

import Button from "@/refresh-components/buttons/Button";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import Switch from "@/refresh-components/inputs/Switch";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { FieldLabel } from "@/components/Field";
import { Section } from "@/layouts/general-layouts";

interface AutoModeToggleProps {
  isAutoMode: boolean;
  onToggle: (nextValue: boolean) => void;
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
      <Switch checked={isAutoMode} onCheckedChange={onToggle} />
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

  const handleToggleAutoMode = (nextIsAutoMode: boolean) => {
    formikProps.setFieldValue("is_auto_mode", nextIsAutoMode);
    formikProps.setFieldValue(
      "selected_model_names",
      modelConfigurations.filter((m) => m.is_visible).map((m) => m.name)
    );
    formikProps.setFieldValue(
      "default_model_name",
      recommendedDefaultModel?.name ?? null
    );
  };

  const selectedModels = formikProps.values.selected_model_names ?? [];
  const defaultModel = formikProps.values.default_model_name;
  const selectedModelSet = new Set(selectedModels);
  const allModelNames = modelConfigurations.map((model) => model.name);
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
      formikProps.setFieldValue("default_model_name", nextDefault);
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
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="auto"
          gap={0.5}
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            height="auto"
            width="fit"
            gap={0.5}
          >
            <Checkbox
              checked={areAllModelsSelected}
              indeterminate={areSomeModelsSelected && !areAllModelsSelected}
              onCheckedChange={() =>
                areAllModelsSelected
                  ? handleClearAllModels()
                  : handleSelectAllModels()
              }
              aria-label="Select all models"
            />
            <Button
              main
              internal
              className="p-0 h-auto rounded-none"
              onClick={() =>
                areAllModelsSelected
                  ? handleClearAllModels()
                  : handleSelectAllModels()
              }
            >
              <Text
                as="span"
                secondaryBody
                className={cn(
                  "text-xs",
                  areSomeModelsSelected ? "text-text-03" : "text-text-02"
                )}
              >
                Select all models
              </Text>
            </Button>
          </Section>
          {areSomeModelsSelected && (
            <Button
              main
              internal
              className="p-0 h-auto rounded-none"
              onClick={handleClearAllModels}
            >
              <Text
                as="span"
                secondaryBody
                className="text-xs text-action-link-05 hover:text-action-link-06"
              >
                Clear all ({selectedModels.length})
              </Text>
            </Button>
          )}
        </Section>
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
                    <Button
                      main
                      internal
                      type="button"
                      disabled={!isSelected}
                      onClick={() => handleSetDefault(modelConfiguration.name)}
                      className={cn(
                        "px-2 py-0.5 rounded transition-all duration-200 ease-in-out",
                        isSelected
                          ? "opacity-100 translate-x-0"
                          : "opacity-0 translate-x-2 pointer-events-none",
                        isDefault
                          ? "bg-action-link-05 font-medium scale-100"
                          : "bg-background-neutral-02 hover:bg-background-neutral-03 scale-95 hover:scale-100"
                      )}
                    >
                      <Text
                        as="span"
                        secondaryBody
                        className={cn(
                          "text-xs",
                          isDefault ? "text-text-inverse" : "text-text-03"
                        )}
                      >
                        {isDefault ? "Default" : "Set as default"}
                      </Text>
                    </Button>
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
