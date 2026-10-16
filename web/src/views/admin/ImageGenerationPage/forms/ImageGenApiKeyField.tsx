"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import type { RichStr } from "@opal/types";
import { ApiTokenField } from "@/lib/api-tokens/components";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import { FormField } from "@/refresh-components/form/FormField";
import type {
  FormValues,
  ImageGenFormChildProps,
} from "@/views/admin/ImageGenerationPage/forms/types";

/** Form values of a form with an API key field. */
export interface ImageGenApiKeyFormValues extends FormValues {
  api_key: ApiTokenValue;
  /** The masked key the config already uses. Display only. */
  api_key_masked?: string;
}

export interface ImageGenApiKeyFieldProps<T extends ImageGenApiKeyFormValues> {
  childProps: ImageGenFormChildProps<T>;
  /** Replaces the shared sub-description, e.g. to say where to get the key. */
  subDescription?: string | RichStr;
  disabled?: boolean;
}

/** The API key field of an image generation form, with the key test result. */
export function ImageGenApiKeyField<T extends ImageGenApiKeyFormValues>({
  childProps,
  subDescription,
  disabled = false,
}: ImageGenApiKeyFieldProps<T>) {
  const t = useTranslations("admin.imageGeneration");
  const {
    formikProps,
    apiStatus,
    showApiMessage,
    errorMessage,
    resetApiState,
    imageProvider,
  } = childProps;
  const apiKey = formikProps.values.api_key;

  // A changed key hides the result of the last test.
  useEffect(() => {
    resetApiState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  return (
    <>
      <ApiTokenField
        platform={imageProvider.provider_name}
        subDescription={subDescription}
        savedMaskedValue={formikProps.values.api_key_masked}
        disabled={childProps.disabled || disabled}
      />
      {showApiMessage && (
        <FormField
          name="api_key"
          state={apiStatus === "error" ? "error" : "idle"}
          className="w-full"
        >
          <FormField.APIMessage
            state={apiStatus}
            messages={{
              loading: t("form.apiKeyTest.loading", {
                title: imageProvider.title,
              }),
              success: t("form.apiKeyTest.success"),
              error: errorMessage || t("form.apiKeyTest.error"),
            }}
          />
        </FormField>
      )}
    </>
  );
}
