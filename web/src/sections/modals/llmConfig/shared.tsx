"use client";

import { useState, useEffect } from "react";
import { FormikProps } from "formik";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import { AgentsMultiSelect } from "@/components/AgentsMultiSelect";
import { useAgents } from "@/hooks/useAgents";
import { ModelConfiguration, SimpleKnownModel } from "@/interfaces/llm";
import { Section } from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import Switch from "@/refresh-components/inputs/Switch";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Text from "@/refresh-components/texts/Text";
import { Button as OpalButton } from "@opal/components";
import { BaseLLMFormValues } from "./formUtils";

// ─── DisplayNameField ────────────────────────────────────────────────────────

interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <InputLayouts.Vertical
      name="name"
      title="Display Name"
      subDescription="Used to identify this provider in the app."
      optional
    >
      <InputTypeInField
        name="name"
        placeholder="Display Name"
        variant={disabled ? "disabled" : undefined}
      />
    </InputLayouts.Vertical>
  );
}

// ─── APIKeyField ─────────────────────────────────────────────────────────────

interface APIKeyFieldProps {
  optional?: boolean;
  providerName?: string;
}

export function APIKeyField({
  optional = false,
  providerName,
}: APIKeyFieldProps) {
  return (
    <InputLayouts.Vertical
      name="api_key"
      title="API Key"
      subDescription={
        providerName
          ? `Paste your API key from ${providerName} to access your models.`
          : "Paste your API key to access your models."
      }
      optional={optional}
    >
      <PasswordInputTypeInField name="api_key" />
    </InputLayouts.Vertical>
  );
}

// ─── SingleDefaultModelField ─────────────────────────────────────────────────

interface SingleDefaultModelFieldProps {
  placeholder?: string;
}

export function SingleDefaultModelField({
  placeholder = "E.g. gpt-4o",
}: SingleDefaultModelFieldProps) {
  return (
    <InputLayouts.Vertical
      name="default_model_name"
      title="Default Model"
      description="The model to use by default for this provider unless otherwise specified."
    >
      <InputTypeInField name="default_model_name" placeholder={placeholder} />
    </InputLayouts.Vertical>
  );
}

// ─── FetchModelsButton ───────────────────────────────────────────────────────

interface FetchModelsButtonProps {
  onFetch: () => Promise<{ models: ModelConfiguration[]; error?: string }>;
  isDisabled?: boolean;
  disabledHint?: string;
  onModelsFetched: (models: ModelConfiguration[]) => void;
  onLoadingChange?: (isLoading: boolean) => void;
  autoFetchOnInitialLoad?: boolean;
}

export function FetchModelsButton({
  onFetch,
  isDisabled = false,
  disabledHint,
  onModelsFetched,
  onLoadingChange,
  autoFetchOnInitialLoad = false,
}: FetchModelsButtonProps) {
  const [isFetchingModels, setIsFetchingModels] = useState(false);
  const [fetchModelsError, setFetchModelsError] = useState("");

  const handleFetchModels = async () => {
    setIsFetchingModels(true);
    onLoadingChange?.(true);
    setFetchModelsError("");

    try {
      const { models, error } = await onFetch();

      if (error) {
        setFetchModelsError(error);
      } else {
        onModelsFetched(models);
      }
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Unknown error occurred";
      setFetchModelsError(errorMessage);
    } finally {
      setIsFetchingModels(false);
      onLoadingChange?.(false);
    }
  };

  // Auto-fetch models on initial load if enabled and not disabled
  useEffect(() => {
    if (autoFetchOnInitialLoad && !isDisabled) {
      handleFetchModels();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-y-1">
      <SimpleTooltip tooltip={isDisabled ? disabledHint : undefined} side="top">
        <div className="w-fit">
          <OpalButton
            type="button"
            onClick={handleFetchModels}
            disabled={isFetchingModels || isDisabled}
          >
            Fetch Available Models
          </OpalButton>
        </div>
      </SimpleTooltip>
      {fetchModelsError && (
        <Text as="p" className="text-xs text-status-error-05 mt-1">
          {fetchModelsError}
        </Text>
      )}
    </div>
  );
}

// ─── AdvancedOptions ─────────────────────────────────────────────────────────

interface AdvancedOptionsProps {
  formikProps: FormikProps<any>;
}

export function AdvancedOptions({ formikProps }: AdvancedOptionsProps) {
  const { agents, isLoading: agentsLoading, error: agentsError } = useAgents();
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  return (
    <>
      <AdvancedOptionsToggle
        showAdvancedOptions={showAdvancedOptions}
        setShowAdvancedOptions={setShowAdvancedOptions}
      />

      {showAdvancedOptions && (
        <>
          <div className="flex flex-col gap-3">
            <Text as="p" headingH3>
              Access Controls
            </Text>
            <IsPublicGroupSelector
              formikProps={formikProps}
              objectName="LLM Provider"
              publicToWhom="Users"
              enforceGroupSelection={true}
              smallLabels={true}
            />
            <AgentsMultiSelect
              formikProps={formikProps}
              agents={agents}
              isLoading={agentsLoading}
              error={agentsError}
              label="Agent Whitelist"
              subtext="Restrict this provider to specific agents."
              disabled={formikProps.values.is_public}
              disabledMessage="This LLM Provider is public and available to all agents."
            />
          </div>
        </>
      )}
    </>
  );
}

// ─── DisplayModels ───────────────────────────────────────────────────────────

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
      <Text as="p" mainUiAction>
        Available Models
      </Text>
      <Text as="p" secondaryBody text03>
        {alternativeText ??
          "Select which models to make available for this provider."}
      </Text>
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
            {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
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
            // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
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
                    {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
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
