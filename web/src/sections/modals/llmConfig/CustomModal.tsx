"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Formik, FormikProps } from "formik";
import { LLMProviderFormProps, ModelConfiguration } from "@/interfaces/llm";
import * as Yup from "yup";
import {
  buildDefaultInitialValues,
  buildOnboardingInitialValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  APIKeyField,
  DisplayNameField,
  FieldSeparator,
  ModelsAccessField,
  LLMConfigurationModalWrapper,
  FieldWrapper,
} from "@/sections/modals/llmConfig/shared";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import KeyValueInput, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import { Button, Card, EmptyMessageCard } from "@opal/components";
import { SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import { markdown } from "@opal/utils";
import { toast } from "@/hooks/useToast";
import { Content } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";

// ─── Model Configuration List ─────────────────────────────────────────────────

const MODEL_GRID_COLS = "grid-cols-[2fr_2fr_minmax(10rem,1fr)_1fr_2.25rem]";

type CustomModelConfiguration = Pick<
  ModelConfiguration,
  "name" | "max_input_tokens" | "supports_image_input"
> & {
  display_name: string;
};

interface ModelConfigurationItemProps {
  model: CustomModelConfiguration;
  onChange: (next: CustomModelConfiguration) => void;
  onRemove: () => void;
  canRemove: boolean;
}

function ModelConfigurationItem({
  model,
  onChange,
  onRemove,
  canRemove,
}: ModelConfigurationItemProps) {
  return (
    <>
      <InputTypeIn
        placeholder="Model name"
        value={model.name}
        onChange={(e) => onChange({ ...model, name: e.target.value })}
        showClearButton={false}
      />
      <InputTypeIn
        placeholder="Display name"
        value={model.display_name}
        onChange={(e) => onChange({ ...model, display_name: e.target.value })}
        showClearButton={false}
      />
      <InputSelect
        value={model.supports_image_input ? "text-image" : "text-only"}
        onValueChange={(value) =>
          onChange({ ...model, supports_image_input: value === "text-image" })
        }
      >
        <InputSelect.Trigger placeholder="Input type" />
        <InputSelect.Content>
          <InputSelect.Item value="text-only">Text Only</InputSelect.Item>
          <InputSelect.Item value="text-image">Text & Image</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
      <InputTypeIn
        placeholder="Default"
        value={model.max_input_tokens?.toString() ?? ""}
        onChange={(e) =>
          onChange({
            ...model,
            max_input_tokens:
              e.target.value === "" ? null : Number(e.target.value),
          })
        }
        showClearButton={false}
        type="number"
      />
      <Button
        disabled={!canRemove}
        prominence="tertiary"
        icon={SvgMinusCircle}
        onClick={onRemove}
      />
    </>
  );
}

interface ModelConfigurationListProps {
  formikProps: FormikProps<{
    model_configurations: CustomModelConfiguration[];
  }>;
}

function ModelConfigurationList({ formikProps }: ModelConfigurationListProps) {
  const models = formikProps.values.model_configurations;

  function handleChange(index: number, next: CustomModelConfiguration) {
    const updated = [...models];
    updated[index] = next;
    formikProps.setFieldValue("model_configurations", updated);
  }

  function handleRemove(index: number) {
    formikProps.setFieldValue(
      "model_configurations",
      models.filter((_, i) => i !== index)
    );
  }

  function handleAdd() {
    formikProps.setFieldValue("model_configurations", [
      ...models,
      {
        name: "",
        display_name: "",
        max_input_tokens: null,
        supports_image_input: false,
      },
    ]);
  }

  return (
    <div className="w-full flex flex-col gap-y-2">
      {models.length > 0 ? (
        <div className={`grid items-center gap-1 ${MODEL_GRID_COLS}`}>
          <div className="pb-1">
            <Text mainUiAction>Model Name</Text>
          </div>
          <Text mainUiAction>Display Name</Text>
          <Text mainUiAction>Input Type</Text>
          <Text mainUiAction>Max Tokens</Text>
          <div aria-hidden />

          {models.map((model, index) => (
            <ModelConfigurationItem
              key={index}
              model={model}
              onChange={(next) => handleChange(index, next)}
              onRemove={() => handleRemove(index)}
              canRemove={models.length > 1}
            />
          ))}
        </div>
      ) : (
        <EmptyMessageCard title="No models added yet." padding="sm" />
      )}

      <Button
        prominence="secondary"
        icon={SvgPlusCircle}
        onClick={handleAdd}
        type="button"
      >
        Add Model
      </Button>
    </div>
  );
}

// ─── Custom Config Processing ─────────────────────────────────────────────────

function keyValueListToDict(items: KeyValue[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const { key, value } of items) {
    if (key.trim() !== "") {
      result[key] = value;
    }
  }
  return result;
}

export default function CustomModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const [isTesting, setIsTesting] = useState(false);
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues = {
    ...buildDefaultInitialValues(
      existingLlmProvider,
      undefined,
      defaultModelName
    ),
    ...(isOnboarding ? buildOnboardingInitialValues() : {}),
    provider: existingLlmProvider?.provider ?? "",
    api_key: existingLlmProvider?.api_key ?? "",
    api_base: existingLlmProvider?.api_base ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    model_configurations: existingLlmProvider?.model_configurations.map(
      (mc) => ({
        name: mc.name,
        display_name: mc.display_name ?? "",
        max_input_tokens: mc.max_input_tokens ?? null,
        supports_image_input: mc.supports_image_input,
      })
    ) ?? [
      {
        name: "",
        display_name: "",
        max_input_tokens: null,
        supports_image_input: false,
      },
    ],
    custom_config_list: existingLlmProvider?.custom_config
      ? Object.entries(existingLlmProvider.custom_config).map(
          ([key, value]) => ({ key, value: String(value) })
        )
      : [],
  };

  const modelConfigurationSchema = Yup.object({
    name: Yup.string().required("Model name is required"),
    max_input_tokens: Yup.number()
      .transform((value, originalValue) =>
        originalValue === "" || originalValue === undefined ? null : value
      )
      .nullable()
      .optional(),
  });

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        provider: Yup.string().required("Provider Name is required"),
        model_configurations: Yup.array(modelConfigurationSchema),
      })
    : Yup.object().shape({
        name: Yup.string().required("Display Name is required"),
        provider: Yup.string().required("Provider Name is required"),
        model_configurations: Yup.array(modelConfigurationSchema),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        const modelConfigurations = values.model_configurations
          .filter((mc) => mc.name.trim() !== "")
          .map((mc) => ({
            name: mc.name,
            display_name: mc.display_name || undefined,
            is_visible: true,
            max_input_tokens: mc.max_input_tokens ?? null,
            supports_image_input: mc.supports_image_input,
            supports_reasoning: false,
          }));

        if (modelConfigurations.length === 0) {
          toast.error("At least one model name is required");
          setSubmitting(false);
          return;
        }

        // Always send custom_config as a dict (even empty) so the backend
        // preserves it as non-null — this is the signal that the provider was
        // created via CustomModal.
        const customConfig = keyValueListToDict(values.custom_config_list);

        if (isOnboarding && onboardingState && onboardingActions) {
          await submitOnboardingProvider({
            providerName: values.provider,
            payload: {
              ...values,
              model_configurations: modelConfigurations,
              custom_config: customConfig,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: true,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          const selectedModelNames = modelConfigurations.map(
            (config) => config.name
          );

          await submitLLMProvider({
            providerName: values.provider,
            values: {
              ...values,
              selected_model_names: selectedModelNames,
              custom_config: customConfig,
            },
            initialValues: {
              ...initialValues,
              custom_config: keyValueListToDict(
                initialValues.custom_config_list
              ),
            },
            modelConfigurations,
            existingLlmProvider,
            shouldMarkAsDefault,
            setIsTesting,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      {(formikProps) => (
        <LLMConfigurationModalWrapper
          providerEndpoint="custom"
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isDirty={formikProps.dirty}
          isTesting={isTesting}
          isSubmitting={formikProps.isSubmitting}
        >
          {!isOnboarding && (
            <FieldWrapper>
              <InputLayouts.Vertical
                name="provider"
                title="Provider Name"
                subDescription={markdown(
                  "Should be one of the providers listed at [LiteLLM](https://docs.litellm.ai/docs/providers)."
                )}
              >
                <InputTypeInField
                  name="provider"
                  placeholder="Provider Name as shown on LiteLLM"
                  variant={existingLlmProvider ? "disabled" : undefined}
                />
              </InputLayouts.Vertical>
            </FieldWrapper>
          )}

          <FieldWrapper>
            <InputLayouts.Vertical
              name="api_base"
              title="API Base URL"
              suffix="optional"
            >
              <InputTypeInField name="api_base" placeholder="https://" />
            </InputLayouts.Vertical>
          </FieldWrapper>

          <FieldWrapper>
            <InputLayouts.Vertical
              name="api_version"
              title="API Version"
              suffix="optional"
            >
              <InputTypeInField name="api_version" />
            </InputLayouts.Vertical>
          </FieldWrapper>

          <APIKeyField
            optional
            subDescription="Paste your API key if your model provider requires authentication."
          />

          <FieldWrapper>
            <Section gap={0.75}>
              <Content
                title="Additional Configs"
                description={markdown(
                  "Add extra properties as needed by the model provider. These are passed to LiteLLM's `completion()` call as [environment variables](https://docs.litellm.ai/docs/set_keys#environment-variables). See [documentation](https://docs.onyx.app/admins/ai_models/custom_inference_provider) for more instructions."
                )}
                widthVariant="full"
                variant="section"
                sizePreset="main-content"
              />

              <KeyValueInput
                items={formikProps.values.custom_config_list}
                onChange={(items) =>
                  formikProps.setFieldValue("custom_config_list", items)
                }
                addButtonLabel="Add Line"
              />
            </Section>
          </FieldWrapper>

          <FieldSeparator />

          {!isOnboarding && (
            <DisplayNameField disabled={!!existingLlmProvider} />
          )}

          <FieldSeparator />

          <Section gap={0.5}>
            <FieldWrapper>
              <Content
                title="Models"
                description="List LLM models you wish to use and their configurations for this provider. See full list of models at LiteLLM."
                variant="section"
                sizePreset="main-content"
                widthVariant="full"
              />
            </FieldWrapper>

            <Card padding="sm">
              <ModelConfigurationList formikProps={formikProps as any} />
            </Card>
          </Section>

          {!isOnboarding && (
            <>
              <FieldSeparator />
              <ModelsAccessField formikProps={formikProps} />
            </>
          )}
        </LLMConfigurationModalWrapper>
      )}
    </Formik>
  );
}
