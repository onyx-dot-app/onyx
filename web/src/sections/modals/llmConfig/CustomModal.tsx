"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { ArrayHelpers, FieldArray, Formik } from "formik";
import { LLMProviderFormProps } from "@/interfaces/llm";
import * as Yup from "yup";
import { LLMConfigurationModalWrapper } from "./LLMConfigurationModalWrapper";
import {
  submitLLMProvider,
  submitOnboardingProvider,
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildOnboardingInitialValues,
} from "./formUtils";
import {
  APIKeyField,
  DisplayNameField,
  FieldSeparator,
  ModelsAccessField,
} from "./shared";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import { ModelConfigurationField } from "@/app/admin/configuration/llm/ModelConfigurationField";
import Text from "@/refresh-components/texts/Text";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgX } from "@opal/icons";
import { toast } from "@/hooks/useToast";

export const CUSTOM_PROVIDER_NAME = "custom";

function customConfigProcessing(customConfigsList: [string, string][]) {
  const customConfig: { [key: string]: string } = {};
  customConfigsList.forEach(([key, value]) => {
    customConfig[key] = value;
  });
  return customConfig;
}

export function CustomModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  onboardingState,
  onboardingActions,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const [isTesting, setIsTesting] = useState(false);
  const { mutate } = useSWRConfig();

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const initialValues = {
    ...buildDefaultInitialValues(existingLlmProvider),
    ...(isOnboarding ? buildOnboardingInitialValues() : {}),
    provider: existingLlmProvider?.provider ?? "",
    api_key: existingLlmProvider?.api_key ?? "",
    api_base: existingLlmProvider?.api_base ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    model_configurations: existingLlmProvider?.model_configurations.map(
      (modelConfiguration) => ({
        ...modelConfiguration,
        max_input_tokens: modelConfiguration.max_input_tokens ?? null,
      })
    ) ?? [
      {
        name: "",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: false,
        supports_reasoning: false,
      },
    ],
    custom_config_list: existingLlmProvider?.custom_config
      ? Object.entries(existingLlmProvider.custom_config)
      : [],
    deployment_name: existingLlmProvider?.deployment_name ?? null,
  };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        provider: Yup.string().required("Provider Name is required"),
        model_configurations: Yup.array(
          Yup.object({
            name: Yup.string().required("Model name is required"),
            is_visible: Yup.boolean().required("Visibility is required"),
            max_input_tokens: Yup.number()
              .transform((value, originalValue) =>
                originalValue === "" || originalValue === undefined
                  ? null
                  : value
              )
              .nullable()
              .optional(),
          })
        ),
        default_model_name: Yup.string().required("Default model is required"),
      })
    : buildDefaultValidationSchema().shape({
        provider: Yup.string().required("Provider Name is required"),
        api_key: Yup.string(),
        api_base: Yup.string(),
        api_version: Yup.string(),
        model_configurations: Yup.array(
          Yup.object({
            name: Yup.string().required("Model name is required"),
            is_visible: Yup.boolean().required("Visibility is required"),
            max_input_tokens: Yup.number()
              .transform((value, originalValue) =>
                originalValue === "" || originalValue === undefined
                  ? null
                  : value
              )
              .nullable()
              .optional(),
          })
        ),
        custom_config_list: Yup.array(),
        deployment_name: Yup.string().nullable(),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        const modelConfigurations = values.model_configurations
          .map((mc) => ({
            name: mc.name,
            is_visible: mc.is_visible,
            max_input_tokens: mc.max_input_tokens ?? null,
            supports_image_input: mc.supports_image_input ?? false,
            supports_reasoning: mc.supports_reasoning ?? false,
          }))
          .filter(
            (mc) => mc.name === values.default_model_name || mc.is_visible
          );

        if (modelConfigurations.length === 0) {
          toast.error("At least one model name is required");
          setSubmitting(false);
          return;
        }

        if (isOnboarding && onboardingState && onboardingActions) {
          await submitOnboardingProvider({
            providerName: values.provider,
            payload: {
              ...values,
              model_configurations: modelConfigurations,
              custom_config: customConfigProcessing(values.custom_config_list),
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: true,
            onClose,
            setIsSubmitting: setSubmitting,
            setApiStatus: () => {},
            setShowApiMessage: () => {},
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
              custom_config: customConfigProcessing(values.custom_config_list),
            },
            initialValues: {
              ...initialValues,
              custom_config: customConfigProcessing(
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
          providerName="Custom LLM"
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isTesting={isTesting}
        >
          {!isOnboarding && (
            <DisplayNameField disabled={!!existingLlmProvider} />
          )}

          <InputLayouts.Vertical
            name="provider"
            title="Provider Name"
            description="Should be one of the providers listed at https://docs.litellm.ai/docs/providers."
          >
            <InputTypeInField
              name="provider"
              placeholder="Name of the custom provider"
            />
          </InputLayouts.Vertical>

          <FieldSeparator />

          <Text as="p" secondaryBody text03>
            Fill in the following as needed. Refer to the LiteLLM documentation
            for the provider specified above to determine which fields are
            required.
          </Text>

          <APIKeyField optional />

          <InputLayouts.Vertical name="api_base" title="API Base" optional>
            <InputTypeInField name="api_base" placeholder="API Base URL" />
          </InputLayouts.Vertical>

          <InputLayouts.Vertical
            name="api_version"
            title="API Version"
            optional
          >
            <InputTypeInField name="api_version" placeholder="API Version" />
          </InputLayouts.Vertical>

          <FieldSeparator />

          <Text as="p" mainUiAction>
            [Optional] Custom Configs
          </Text>
          <Text as="p" secondaryBody text03>
            <div>
              Additional configurations needed by the model provider. These are
              passed to LiteLLM via environment variables and as arguments into
              the completion call.
            </div>
            <div className="mt-2">
              For example, when configuring the Cloudflare provider, you would
              need to set CLOUDFLARE_ACCOUNT_ID as the key and your Cloudflare
              account ID as the value.
            </div>
          </Text>

          <FieldArray
            name="custom_config_list"
            render={(arrayHelpers: ArrayHelpers<any[]>) => (
              <div className="w-full flex flex-col gap-4">
                {formikProps.values.custom_config_list.map((_, index) => (
                  <div key={index} className="flex w-full gap-2 items-start">
                    <div className="flex-1 min-w-0 flex flex-col gap-3 border border-border-02 p-3 rounded-08">
                      <InputLayouts.Vertical
                        name={`custom_config_list[${index}][0]`}
                        title="Key"
                      >
                        <InputTypeInField
                          name={`custom_config_list[${index}][0]`}
                          placeholder="e.g. CLOUDFLARE_ACCOUNT_ID"
                        />
                      </InputLayouts.Vertical>
                      <InputLayouts.Vertical
                        name={`custom_config_list[${index}][1]`}
                        title="Value"
                      >
                        <InputTypeInField
                          name={`custom_config_list[${index}][1]`}
                          placeholder="Value"
                        />
                      </InputLayouts.Vertical>
                    </div>
                    <div className="pt-6">
                      <IconButton
                        icon={SvgX}
                        onClick={() => arrayHelpers.remove(index)}
                        secondary
                      />
                    </div>
                  </div>
                ))}
                <CreateButton onClick={() => arrayHelpers.push(["", ""])}>
                  Add New
                </CreateButton>
              </div>
            )}
          />

          <FieldSeparator />

          <ModelConfigurationField
            name="model_configurations"
            formikProps={formikProps as any}
          />

          <FieldSeparator />

          <InputLayouts.Vertical
            name="default_model_name"
            title="Default Model"
            description="The model to use by default for this provider. Must be one of the models listed above."
          >
            <InputTypeInField
              name="default_model_name"
              placeholder="e.g. gpt-4"
            />
          </InputLayouts.Vertical>

          {!isOnboarding && <ModelsAccessField formikProps={formikProps} />}
        </LLMConfigurationModalWrapper>
      )}
    </Formik>
  );
}
