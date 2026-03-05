"use client";

import { useState, useEffect } from "react";
import { FormikProps } from "formik";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import { AgentsMultiSelect } from "@/components/AgentsMultiSelect";
import { useAgents } from "@/hooks/useAgents";
import { ModelConfiguration, SimpleKnownModel } from "@/interfaces/llm";
import * as InputLayouts from "@/layouts/input-layouts";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import Switch from "@/refresh-components/inputs/Switch";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Text from "@/refresh-components/texts/Text";
import { Button as OpalButton, LineItemButton, Tag } from "@opal/components";
import { BaseLLMFormValues } from "./formUtils";
import { WithoutStyles } from "@opal/types";
import Separator from "@/refresh-components/Separator";
import { Section } from "@/layouts/general-layouts";
import { Hoverable } from "@opal/core";
import { SvgCheck } from "@opal/icons";

export function FieldSeparator() {
  return <Separator noPadding className="px-2" />;
}

type FieldWrapperProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>>;

function FieldWrapper(props: FieldWrapperProps) {
  return <div {...props} className="p-2 w-full" />;
}

// ─── DisplayNameField ────────────────────────────────────────────────────────

interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <FieldWrapper>
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
    </FieldWrapper>
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
    <FieldWrapper>
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
    </FieldWrapper>
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

// ─── DisplayModelsField ─────────────────────────────────────────────────────

export interface DisplayModelsFieldProps<T> {
  formikProps: FormikProps<T>;
  modelConfigurations: ModelConfiguration[];
  noModelConfigurationsMessage?: string;
  isLoading?: boolean;
  recommendedDefaultModel: SimpleKnownModel | null;
  shouldShowAutoUpdateToggle: boolean;
}

export function DisplayModelsField<T extends BaseLLMFormValues>({
  formikProps,
  modelConfigurations,
  noModelConfigurationsMessage,
  isLoading,
  recommendedDefaultModel,
  shouldShowAutoUpdateToggle,
}: DisplayModelsFieldProps<T>) {
  const isAutoMode = formikProps.values.is_auto_mode;
  const selectedModels = formikProps.values.selected_model_names ?? [];
  const defaultModel = formikProps.values.default_model_name;

  function handleCheckboxChange(modelName: string, checked: boolean) {
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
  }

  function handleSetDefault(modelName: string) {
    formikProps.setFieldValue("default_model_name", modelName);
  }

  function handleToggleAutoMode(nextIsAutoMode: boolean) {
    formikProps.setFieldValue("is_auto_mode", nextIsAutoMode);
    formikProps.setFieldValue(
      "selected_model_names",
      modelConfigurations.filter((m) => m.is_visible).map((m) => m.name)
    );
    formikProps.setFieldValue(
      "default_model_name",
      recommendedDefaultModel?.name ?? null
    );
  }

  const visibleModels = modelConfigurations.filter((m) => m.is_visible);

  return (
    <FieldWrapper>
      <Section gap={0.5}>
        <InputLayouts.Horizontal
          title="Models"
          description="Select models to make available for this provider."
        />

        <Section gap={0.25}>
          {isAutoMode
            ? // Auto mode: read-only display
              visibleModels.map((model) => (
                <Hoverable.Root
                  key={model.name}
                  group="asdf"
                  widthVariant="full"
                >
                  <LineItemButton
                    variant="section"
                    sizePreset="main-ui"
                    prominence="heavy"
                    selected
                    icon={() => <Checkbox checked />}
                    title={model.display_name || model.name}
                    rightChildren={
                      model.name === defaultModel ? (
                        <Section>
                          <Tag title="Default Model" color="blue" />
                        </Section>
                      ) : undefined
                    }
                  />
                </Hoverable.Root>
              ))
            : // Manual mode: checkbox selection
              modelConfigurations.map((modelConfiguration) => {
                const isSelected = selectedModels.includes(
                  modelConfiguration.name
                );
                const isDefault = defaultModel === modelConfiguration.name;

                return (
                  <Hoverable.Root
                    group="LLMConfigurationButton"
                    widthVariant="full"
                  >
                    <LineItemButton
                      key={modelConfiguration.name}
                      variant="section"
                      sizePreset="main-ui"
                      prominence="heavy"
                      selected={isSelected}
                      icon={() => <Checkbox checked={isSelected} />}
                      title={modelConfiguration.name}
                      onClick={() =>
                        handleCheckboxChange(
                          modelConfiguration.name,
                          !isSelected
                        )
                      }
                      rightChildren={
                        isSelected ? (
                          isDefault ? (
                            <Section>
                              <Tag color="blue" title="Default Model" />
                            </Section>
                          ) : (
                            <Hoverable.Item
                              group="LLMConfigurationButton"
                              variant="opacity-on-hover"
                            >
                              <OpalButton
                                size="sm"
                                prominence="internal"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSetDefault(modelConfiguration.name);
                                }}
                                type="button"
                              >
                                Set as default
                              </OpalButton>
                            </Hoverable.Item>
                          )
                        ) : undefined
                      }
                    />
                  </Hoverable.Root>
                );
              })}
        </Section>

        {shouldShowAutoUpdateToggle && (
          <InputLayouts.Horizontal
            title="Auto Update"
            description="Update the available models when new models are released."
          >
            <Switch
              checked={isAutoMode}
              onCheckedChange={handleToggleAutoMode}
            />
          </InputLayouts.Horizontal>
        )}
      </Section>
    </FieldWrapper>
  );
}
