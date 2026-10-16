"use client";

import React, { useMemo } from "react";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { InputTypeIn } from "@opal/components";
import { markdown } from "@opal/utils";
import { EMPTY_API_TOKEN_VALUE } from "@/lib/api-tokens/constants";
import { initialApiTokenValue } from "@/lib/api-tokens/utils";
import { apiTokenSchema } from "@/lib/api-tokens/validation";
import {
  ImageGenApiKeyField,
  type ImageGenApiKeyFormValues,
} from "@/views/admin/ImageGenerationPage/forms/ImageGenApiKeyField";
import { ImageGenFormWrapper } from "@/views/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/views/admin/ImageGenerationPage/forms/types";
import { ImageGenerationCredentials } from "@/views/admin/ImageGenerationPage/svc";
import { ImageProvider } from "@/views/admin/ImageGenerationPage/constants";
import {
  parseAzureTargetUri,
  isValidAzureTargetUri,
} from "@/lib/azureTargetUri";

// Azure form values - target URI and API key
interface AzureFormValues extends ImageGenApiKeyFormValues {
  target_uri: string;
}

const initialValues: AzureFormValues = {
  target_uri: "",
  api_key: EMPTY_API_TOKEN_VALUE,
};

/** Azure portal page that issues both the target URI and the API key. */
const AZURE_OPENAI_URL = "https://oai.azure.com";

function AzureFormFields(props: ImageGenFormChildProps<AzureFormValues>) {
  const t = useTranslations("admin.imageGeneration");
  const tPlaceholders = useTranslations("common.placeholders");
  const { formikProps, disabled } = props;

  return (
    <>
      {/* Target URI field */}
      <FormikField<string>
        name="target_uri"
        render={(field, _helper, meta, state) => (
          <FormField name="target_uri" state={state} className="w-full">
            <FormField.Label>{t("form.targetUri.label")}</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder={tPlaceholders("azure.imageGenerationsUrl")}
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: t.rich("form.targetUri.idle", {
                  link: (chunks) => (
                    <a
                      href={AZURE_OPENAI_URL}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      {chunks}
                    </a>
                  ),
                }),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      <ImageGenApiKeyField
        childProps={props}
        subDescription={markdown(
          t.markup("form.azureApiKey.idle", {
            link: (chunks) => `[${chunks}](${AZURE_OPENAI_URL})`,
          })
        )}
        disabled={!formikProps.values.target_uri?.trim()}
      />
    </>
  );
}

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  imageProvider: ImageProvider
): Partial<AzureFormValues> {
  // Reconstruct target_uri from credentials
  let targetUri = "";
  if (credentials.api_base && credentials.api_version) {
    const deployment = credentials.deployment_name || imageProvider.model_name;
    targetUri = `${credentials.api_base}/openai/deployments/${deployment}/images/generations?api-version=${credentials.api_version}`;
  }

  return {
    api_key: initialApiTokenValue(credentials.api_token_id),
    api_key_masked: credentials.api_key ?? undefined,
    target_uri: targetUri,
  };
}

function transformValues(
  values: AzureFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  // Parse target_uri to extract api_base, api_version, deployment_name
  let apiBase: string | undefined;
  let apiVersion: string | undefined;
  let deploymentName: string | undefined;
  let modelName = imageProvider.model_name;

  if (values.target_uri) {
    try {
      const parsed = parseAzureTargetUri(values.target_uri);
      apiBase = parsed.url.origin;
      apiVersion = parsed.apiVersion;
      deploymentName = parsed.deploymentName || undefined;
      // For Azure, use deployment name as model name
      modelName = deploymentName || imageProvider.model_name;
    } catch (error) {
      console.error("Failed to parse target_uri:", error);
    }
  }

  return {
    modelName,
    imageProviderId: imageProvider.image_provider_id,
    provider: "azure",
    apiKey: values.api_key,
    apiBase,
    apiVersion,
    deploymentName,
  };
}

export function AzureImageGenForm(props: ImageGenFormBaseProps) {
  const t = useTranslations("admin.imageGeneration");
  const { imageProvider, existingConfig } = props;

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        target_uri: Yup.string()
          .required(t("form.targetUri.required"))
          .test("valid-target-uri", t("form.targetUri.invalid"), (value) =>
            value ? isValidAzureTargetUri(value) : false
          ),
        api_key: apiTokenSchema(t("form.apiKey.required")),
      }),
    [t]
  );

  return (
    <ImageGenFormWrapper<AzureFormValues>
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
      {(childProps) => <AzureFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
