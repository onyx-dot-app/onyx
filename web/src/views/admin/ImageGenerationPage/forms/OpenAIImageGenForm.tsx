"use client";

import React, { useMemo } from "react";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
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

// OpenAI form values - just API key
type OpenAIFormValues = ImageGenApiKeyFormValues;

const initialValues: OpenAIFormValues = {
  api_key: EMPTY_API_TOKEN_VALUE,
};

function OpenAIFormFields(props: ImageGenFormChildProps<OpenAIFormValues>) {
  return <ImageGenApiKeyField childProps={props} />;
}

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  _imageProvider: ImageProvider
): Partial<OpenAIFormValues> {
  return {
    api_key: initialApiTokenValue(credentials.api_token_id),
    api_key_masked: credentials.api_key ?? undefined,
  };
}

function transformValues(
  values: OpenAIFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: "openai",
    apiKey: values.api_key,
  };
}

export function OpenAIImageGenForm(props: ImageGenFormBaseProps) {
  const t = useTranslations("admin.imageGeneration");
  const { imageProvider, existingConfig } = props;

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        api_key: apiTokenSchema(t("form.apiKey.required")),
      }),
    [t]
  );

  return (
    <ImageGenFormWrapper<OpenAIFormValues>
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
      {(childProps) => <OpenAIFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
