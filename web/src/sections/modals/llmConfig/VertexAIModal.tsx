"use client";

import { useSWRConfig } from "swr";
import { FileUploadFormField } from "@/components/Field";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import {
  useInitialValues,
  buildValidationSchema,
  buildAvailableModelConfigurations,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";

const VERTEXAI_DEFAULT_LOCATION = "global";

interface VertexAIModalValues extends BaseLLMFormValues {
  custom_config: {
    vertex_credentials: string;
    vertex_location: string;
  };
}

export default function VertexAIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    LLMProviderName.VERTEX_AI
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: VertexAIModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.VERTEX_AI,
      existingLlmProvider
    ),
    custom_config: {
      vertex_credentials:
        (existingLlmProvider?.custom_config?.vertex_credentials as string) ??
        "",
      vertex_location:
        (existingLlmProvider?.custom_config?.vertex_location as string) ??
        VERTEXAI_DEFAULT_LOCATION,
    },
  } as VertexAIModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    extra: {
      custom_config: Yup.object({
        vertex_credentials: Yup.string().required(
          "Credentials file is required"
        ),
        vertex_location: Yup.string(),
      }),
    },
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.VERTEX_AI}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(
            ([key, v]) => key === "vertex_credentials" || v !== ""
          )
        );

        const submitValues = {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: LLMProviderName.VERTEX_AI,
            payload: {
              ...submitValues,
              model_configurations: modelConfigsToUse,
              is_auto_mode: values.is_auto_mode,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: LLMProviderName.VERTEX_AI,
            values: submitValues,
            initialValues,
            modelConfigurations,
            existingLlmProvider,
            shouldMarkAsDefault,
            setStatus,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      <InputLayouts.FieldPadder>
        <InputLayouts.Vertical
          name="custom_config.vertex_location"
          title="Google Cloud Region Name"
          subDescription="Region where your Google Vertex AI models are hosted. See full list of regions supported at Google Cloud."
        >
          <InputTypeInField
            name="custom_config.vertex_location"
            placeholder={VERTEXAI_DEFAULT_LOCATION}
          />
        </InputLayouts.Vertical>
      </InputLayouts.FieldPadder>

      <InputLayouts.FieldPadder>
        <InputLayouts.Vertical
          name="custom_config.vertex_credentials"
          title="API Key"
          subDescription="Attach your API key JSON from Google Cloud to access your models."
        >
          <FileUploadFormField
            name="custom_config.vertex_credentials"
            label=""
          />
        </InputLayouts.Vertical>
      </InputLayouts.FieldPadder>

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField
        modelConfigurations={modelConfigurations}
        recommendedDefaultModel={
          wellKnownLLMProvider?.recommended_default_model ?? null
        }
        shouldShowAutoUpdateToggle={true}
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
