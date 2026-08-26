"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { InputTypeIn } from "@opal/components";
import InputFile from "@/refresh-components/inputs/InputFile";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ImageGenFormWrapper } from "@/views/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/views/admin/ImageGenerationPage/forms/types";
import { ImageProvider } from "@/views/admin/ImageGenerationPage/constants";
import { ImageGenerationCredentials } from "@/views/admin/ImageGenerationPage/svc";
import { useSettings } from "@/lib/settings/hooks";

const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DEFAULT_LOCATION = "global";

// Kept in sync with backend onyx.llm.well_known_providers.constants
const AUTH_METHOD_SERVICE_ACCOUNT = "service_account_json";
const AUTH_METHOD_WORKLOAD_IDENTITY = "workload_identity";

// Vertex form values
interface VertexImageGenFormValues {
  custom_config: {
    vertex_auth_method: string;
    vertex_credentials: string;
    vertex_location: string;
    vertex_project: string;
  };
}

const initialValues: VertexImageGenFormValues = {
  custom_config: {
    vertex_auth_method: AUTH_METHOD_SERVICE_ACCOUNT,
    vertex_credentials: "",
    vertex_location: VERTEXAI_DEFAULT_LOCATION,
    vertex_project: "",
  },
};

const SERVICE_ACCOUNTS_URL =
  "https://console.cloud.google.com/projectselector2/iam-admin/serviceaccounts?supportedpurview=project";
const VERTEX_LOCATIONS_DOCS_URL =
  "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations";

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  _imageProvider: ImageProvider
): Partial<VertexImageGenFormValues> {
  return {
    custom_config: {
      vertex_auth_method:
        credentials.custom_config?.vertex_auth_method ||
        AUTH_METHOD_SERVICE_ACCOUNT,
      vertex_credentials: credentials.custom_config?.vertex_credentials || "",
      vertex_location:
        credentials.custom_config?.vertex_location || VERTEXAI_DEFAULT_LOCATION,
      vertex_project: credentials.custom_config?.vertex_project || "",
    },
  };
}

function transformValues(
  values: VertexImageGenFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  const authMethod = values.custom_config.vertex_auth_method;
  const isWorkloadIdentity = authMethod === AUTH_METHOD_WORKLOAD_IDENTITY;

  const customConfig: Record<string, string> = {
    vertex_auth_method: authMethod,
    vertex_location: values.custom_config.vertex_location,
  };
  if (isWorkloadIdentity) {
    customConfig.vertex_project = values.custom_config.vertex_project;
  } else {
    customConfig.vertex_credentials = values.custom_config.vertex_credentials;
  }

  return {
    modelName: imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: VERTEXAI_PROVIDER_NAME,
    customConfig,
  };
}

function VertexFormFields(
  props: ImageGenFormChildProps<VertexImageGenFormValues>
) {
  const t = useTranslations("admin.imageGeneration");
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
    disabled,
    imageProvider,
    formikProps,
  } = props;

  const settings = useSettings();
  // Workload Identity relies on ambient GKE credentials, which don't exist in
  // multi-tenant/cloud deployments — only offer it for self-hosted installs.
  const showAuthMethodSelector = !!settings.hooks_enabled;

  const authMethod = formikProps.values.custom_config.vertex_auth_method;
  const isWorkloadIdentity = authMethod === AUTH_METHOD_WORKLOAD_IDENTITY;

  return (
    <>
      {showAuthMethodSelector && (
        <FormikField<string>
          name="custom_config.vertex_auth_method"
          render={(field, helper, _meta, state) => (
            <FormField
              name="custom_config.vertex_auth_method"
              state={state}
              className="w-full"
            >
              <FormField.Label>{t("form.authMethod.label")}</FormField.Label>
              <FormField.Control>
                <InputSelect
                  value={field.value}
                  onValueChange={(value) => helper.setValue(value)}
                  disabled={disabled}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    <InputSelect.Item
                      value={AUTH_METHOD_SERVICE_ACCOUNT}
                      description={t(
                        "form.authMethod.serviceAccount.description"
                      )}
                    >
                      {t("form.authMethod.serviceAccount.label")}
                    </InputSelect.Item>
                    <InputSelect.Item
                      value={AUTH_METHOD_WORKLOAD_IDENTITY}
                      description={t(
                        "form.authMethod.workloadIdentity.description"
                      )}
                    >
                      {t("form.authMethod.workloadIdentity.label")}
                    </InputSelect.Item>
                  </InputSelect.Content>
                </InputSelect>
              </FormField.Control>
              <FormField.Message
                messages={{
                  idle: t("form.authMethod.idle"),
                }}
              />
            </FormField>
          )}
        />
      )}

      {/* Service Account JSON: credentials file */}
      {!isWorkloadIdentity && (
        <FormikField<string>
          name="custom_config.vertex_credentials"
          render={(field, helper, meta, state) => (
            <FormField
              name="custom_config.vertex_credentials"
              state={apiStatus === "error" ? "error" : state}
              className="w-full"
            >
              <FormField.Label>{t("form.credentials.label")}</FormField.Label>
              <FormField.Control>
                <InputFile
                  setValue={(value) => helper.setValue(value)}
                  error={apiStatus === "error"}
                  onBlur={field.onBlur}
                  disabled={disabled}
                  accept="application/json"
                  placeholder={t("form.credentials.placeholder")}
                />
              </FormField.Control>
              {showApiMessage ? (
                <FormField.APIMessage
                  state={apiStatus}
                  messages={{
                    loading: t("form.credentialsTest.loading", {
                      title: imageProvider.title,
                    }),
                    success: t("form.credentialsTest.success"),
                    error: errorMessage || t("form.credentialsTest.error"),
                  }}
                />
              ) : (
                <FormField.Message
                  messages={{
                    idle: t.rich("form.credentials.idle", {
                      link: (chunks) => (
                        <InlineExternalLink href={SERVICE_ACCOUNTS_URL}>
                          {chunks}
                        </InlineExternalLink>
                      ),
                    }),
                    error: meta.error,
                  }}
                />
              )}
            </FormField>
          )}
        />
      )}

      {/* Workload Identity: explicit GCP project ID */}
      {isWorkloadIdentity && (
        <FormikField<string>
          name="custom_config.vertex_project"
          render={(field, helper, meta, state) => (
            <FormField
              name="custom_config.vertex_project"
              state={apiStatus === "error" ? "error" : state}
              className="w-full"
            >
              <FormField.Label>{t("form.projectId.label")}</FormField.Label>
              <FormField.Control>
                <InputTypeIn
                  value={field.value}
                  onChange={(e) => helper.setValue(e.target.value)}
                  onBlur={field.onBlur}
                  placeholder="my-vertex-project"
                  variant={disabled ? "disabled" : undefined}
                />
              </FormField.Control>
              {showApiMessage ? (
                <FormField.APIMessage
                  state={apiStatus}
                  messages={{
                    loading: t("form.credentialsTest.loading", {
                      title: imageProvider.title,
                    }),
                    success: t("form.credentialsTest.success"),
                    error: errorMessage || t("form.credentialsTest.error"),
                  }}
                />
              ) : (
                <FormField.Message
                  messages={{
                    idle: t("form.projectId.idle"),
                    error: meta.error,
                  }}
                />
              )}
            </FormField>
          )}
        />
      )}

      {/* Location field */}
      <FormikField<string>
        name="custom_config.vertex_location"
        render={(field, helper, meta, state) => (
          <FormField
            name="custom_config.vertex_location"
            state={state}
            className="w-full"
          >
            <FormField.Label>{t("form.location.label")}</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                value={field.value}
                onChange={(e) => helper.setValue(e.target.value)}
                onBlur={field.onBlur}
                placeholder="global"
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: t.rich("form.location.idle", {
                  link: (chunks) => (
                    <InlineExternalLink href={VERTEX_LOCATIONS_DOCS_URL}>
                      {chunks}
                    </InlineExternalLink>
                  ),
                }),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
    </>
  );
}

export function VertexImageGenForm(props: ImageGenFormBaseProps) {
  const t = useTranslations("admin.imageGeneration");
  const { imageProvider, existingConfig } = props;

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        custom_config: Yup.object().shape({
          vertex_auth_method: Yup.string().required(
            t("form.authMethod.required")
          ),
          vertex_location: Yup.string().required(t("form.location.required")),
          vertex_credentials: Yup.string().when("vertex_auth_method", {
            is: AUTH_METHOD_SERVICE_ACCOUNT,
            then: (schema) => schema.required(t("form.credentials.required")),
            otherwise: (schema) => schema.notRequired(),
          }),
          vertex_project: Yup.string().when("vertex_auth_method", {
            is: AUTH_METHOD_WORKLOAD_IDENTITY,
            then: (schema) => schema.required(t("form.projectId.required")),
            otherwise: (schema) => schema.notRequired(),
          }),
        }),
      }),
    [t]
  );

  return (
    <ImageGenFormWrapper<VertexImageGenFormValues>
      {...props}
      title={
        existingConfig
          ? t("form.editHeader.title", { title: imageProvider.title })
          : t("form.connectHeader.title", { title: imageProvider.title })
      }
      description={t(imageProvider.descriptionKey)}
      initialValues={initialValues}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={(values) => transformValues(values, imageProvider)}
    >
      {(childProps) => <VertexFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
