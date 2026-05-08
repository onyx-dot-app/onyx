"use client";

import { useEffect } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { FileUploadFormField } from "@/components/Field";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Card, MessageCard } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { InputDivider, InputPadder, InputVertical } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import * as Yup from "yup";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import { toast } from "@/hooks/useToast";
import { useSettingsContext } from "@/providers/SettingsProvider";

const VERTEXAI_DEFAULT_LOCATION = "global";

const AUTH_METHOD_SERVICE_ACCOUNT = "service_account_json";
const AUTH_METHOD_WORKLOAD_IDENTITY = "workload_identity";

const FIELD_VERTEX_AUTH_METHOD = "custom_config.vertex_auth_method";
const FIELD_VERTEX_CREDENTIALS = "custom_config.vertex_credentials";
const FIELD_VERTEX_LOCATION = "custom_config.vertex_location";
const FIELD_VERTEX_PROJECT = "custom_config.vertex_project";

interface VertexAIModalValues extends BaseLLMFormValues {
  custom_config: {
    vertex_auth_method: string;
    vertex_credentials: string;
    vertex_location: string;
    vertex_project: string;
  };
}

interface VertexAIModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function VertexAIModalInternals({
  existingLlmProvider,
  isOnboarding,
}: VertexAIModalInternalsProps) {
  const formikProps = useFormikContext<VertexAIModalValues>();
  const authMethod = formikProps.values.custom_config?.vertex_auth_method;
  const settingsContext = useSettingsContext();
  const isMultiTenant = !settingsContext.settings.hooks_enabled;

  useEffect(() => {
    if (authMethod === AUTH_METHOD_WORKLOAD_IDENTITY) {
      formikProps.setFieldValue(FIELD_VERTEX_CREDENTIALS, "");
    } else if (authMethod === AUTH_METHOD_SERVICE_ACCOUNT) {
      formikProps.setFieldValue(FIELD_VERTEX_PROJECT, "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authMethod]);

  const showAuthMethodSelector = !isMultiTenant;

  return (
    <>
      <InputPadder>
        <Section gap={1}>
          {showAuthMethodSelector && (
            <InputVertical
              withLabel={FIELD_VERTEX_AUTH_METHOD}
              title="Authentication Method"
              subDescription="Choose how Onyx should authenticate with Google Vertex AI."
            >
              <InputSelect
                value={authMethod || AUTH_METHOD_SERVICE_ACCOUNT}
                onValueChange={(value) =>
                  formikProps.setFieldValue(FIELD_VERTEX_AUTH_METHOD, value)
                }
              >
                <InputSelect.Trigger
                  defaultValue={AUTH_METHOD_SERVICE_ACCOUNT}
                />
                <InputSelect.Content>
                  <InputSelect.Item
                    value={AUTH_METHOD_SERVICE_ACCOUNT}
                    description="Upload a GCP service account key JSON file"
                  >
                    Service Account JSON
                  </InputSelect.Item>
                  <InputSelect.Item
                    value={AUTH_METHOD_WORKLOAD_IDENTITY}
                    description="Use the pod's ambient GCP credentials (GKE Workload Identity)"
                  >
                    Workload Identity (GKE)
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </InputVertical>
          )}

          <InputVertical
            withLabel={FIELD_VERTEX_LOCATION}
            title="Google Cloud Region Name"
            subDescription="Region where your Google Vertex AI models are hosted. See full list of regions supported at Google Cloud."
          >
            <InputTypeInField
              name={FIELD_VERTEX_LOCATION}
              placeholder={VERTEXAI_DEFAULT_LOCATION}
            />
          </InputVertical>
        </Section>
      </InputPadder>

      {authMethod === AUTH_METHOD_SERVICE_ACCOUNT && (
        <InputPadder>
          <InputVertical
            withLabel={FIELD_VERTEX_CREDENTIALS}
            title="API Key"
            subDescription="Attach your API key JSON from Google Cloud to access your models."
          >
            <FileUploadFormField name={FIELD_VERTEX_CREDENTIALS} label="" />
          </InputVertical>
        </InputPadder>
      )}

      {authMethod === AUTH_METHOD_WORKLOAD_IDENTITY && (
        <>
          <InputPadder>
            <MessageCard
              variant="info"
              title="Onyx will use the pod's ambient Google Cloud credentials (via google.auth.default). Ensure the Kubernetes ServiceAccount is bound to a GCP Service Account with access to Vertex AI."
            />
          </InputPadder>
          <Card background="light" border="none" padding="sm">
            <InputVertical
              withLabel={FIELD_VERTEX_PROJECT}
              title="GCP Project ID"
              subDescription="The GCP project where Vertex AI is enabled. Required because ADC cannot reliably infer the target project under service-account impersonation."
            >
              <InputTypeInField
                name={FIELD_VERTEX_PROJECT}
                placeholder="my-vertex-project"
              />
            </InputVertical>
          </Card>
        </>
      )}

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputDivider />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function VertexAIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: VertexAIModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.VERTEX_AI,
      existingLlmProvider
    ),
    custom_config: {
      vertex_auth_method:
        (existingLlmProvider?.custom_config?.vertex_auth_method as string) ??
        AUTH_METHOD_SERVICE_ACCOUNT,
      vertex_credentials:
        (existingLlmProvider?.custom_config?.vertex_credentials as string) ??
        "",
      vertex_location:
        (existingLlmProvider?.custom_config?.vertex_location as string) ??
        VERTEXAI_DEFAULT_LOCATION,
      vertex_project:
        (existingLlmProvider?.custom_config?.vertex_project as string) ?? "",
    },
  } as VertexAIModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    extra: {
      custom_config: Yup.object({
        vertex_auth_method: Yup.string().required(
          "Authentication method is required"
        ),
        vertex_location: Yup.string(),
        vertex_credentials: Yup.string().when("vertex_auth_method", {
          is: AUTH_METHOD_SERVICE_ACCOUNT,
          then: (schema) => schema.required("Credentials file is required"),
          otherwise: (schema) => schema.notRequired(),
        }),
        vertex_project: Yup.string().when("vertex_auth_method", {
          is: AUTH_METHOD_WORKLOAD_IDENTITY,
          then: (schema) => schema.required("GCP Project ID is required"),
          otherwise: (schema) => schema.notRequired(),
        }),
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
            ([key, v]) => key === "vertex_auth_method" || v !== ""
          )
        );

        const submitValues = {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.VERTEX_AI,
          values: submitValues,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? "Provider updated successfully!"
                  : "Provider enabled successfully!"
              );
            }
          },
        });
      }}
    >
      <VertexAIModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
