"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Formik } from "formik";
import { LLMProviderFormProps } from "@/interfaces/llm";
import * as Yup from "yup";
import {
  submitLLMProvider,
  submitOnboardingProvider,
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildOnboardingInitialValues,
} from "@/sections/modals/llmConfig/formUtils";
import {
  DisplayNameField,
  FieldSeparator,
  ModelsAccessField,
  LLMConfigurationModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { toast } from "@/hooks/useToast";
import { Content } from "@opal/layouts";

function customConfigProcessing(customConfigsList: [string, string][]) {
  const customConfig: { [key: string]: string } = {};
  customConfigsList.forEach(([key, value]) => {
    customConfig[key] = value;
  });
  return customConfig;
}

export default function CustomModal({
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

  const modelConfigurationSchema = Yup.object({
    name: Yup.string().required("Model name is required"),
    is_visible: Yup.boolean().required("Visibility is required"),
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
        default_model_name: Yup.string().required("Default model is required"),
      })
    : buildDefaultValidationSchema().shape({
        provider: Yup.string().required("Provider Name is required"),
        api_key: Yup.string(),
        api_base: Yup.string(),
        api_version: Yup.string(),
        model_configurations: Yup.array(modelConfigurationSchema),
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
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isTesting={isTesting}
        >
          {!isOnboarding && (
            <DisplayNameField disabled={!!existingLlmProvider} />
          )}

          <FieldSeparator />

          <Content
            title="Provider Configs"
            description="Add properties as needed by the model provider. This is passed to LiteLLM completion() call as arguments in the environment variable. See LiteLLM documentation for more instructions."
            variant="section"
            sizePreset="main-ui"
          />

          {/* TODO: Provider config fields (provider name, API key, API base, API version, custom configs) */}

          <FieldSeparator />

          <Content
            title="Models"
            description="List LLM models you wish to use and their configurations for this provider. See full list of models at LiteLLM."
            variant="section"
            sizePreset="main-ui"
          />

          {/* TODO: Model configuration fields (model list, default model selection) */}

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
