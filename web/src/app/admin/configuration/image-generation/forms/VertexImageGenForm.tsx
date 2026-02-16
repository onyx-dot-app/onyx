"use client";

import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputFile from "@/refresh-components/inputs/InputFile";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ImageGenFormWrapper } from "./ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "./types";
import { ImageProvider } from "../constants";
import { ImageGenerationCredentials } from "@/lib/configuration/imageConfigurationService";

const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DEFAULT_LOCATION = "global";

// Vertex form values
interface VertexImageGenFormValues {
  custom_config: {
    vertex_credentials: string;
    vertex_location: string;
  };
}

const initialValues: VertexImageGenFormValues = {
  custom_config: {
    vertex_credentials: "",
    vertex_location: VERTEXAI_DEFAULT_LOCATION,
  },
};

const validationSchema = Yup.object().shape({
  custom_config: Yup.object().shape({
    vertex_credentials: Yup.string().required("Credentials file is required"),
    vertex_location: Yup.string().required("Location is required"),
  }),
});

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  _imageProvider: ImageProvider
): Partial<VertexImageGenFormValues> {
  return {
    custom_config: {
      vertex_credentials: credentials.custom_config?.vertex_credentials || "",
      vertex_location:
        credentials.custom_config?.vertex_location || VERTEXAI_DEFAULT_LOCATION,
    },
  };
}

function transformValues(
  values: VertexImageGenFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: VERTEXAI_PROVIDER_NAME,
    customConfig: {
      vertex_credentials: values.custom_config.vertex_credentials,
      vertex_location: values.custom_config.vertex_location,
    },
  };
}

function VertexFormFields(
  props: ImageGenFormChildProps<VertexImageGenFormValues>
) {
  const { apiStatus, showApiMessage, errorMessage, disabled, imageProvider } =
    props;

  return (
    <>
      {/* Credentials File field */}
      <FormikField<string>
        name="custom_config.vertex_credentials"
        render={(field, helper, meta, state) => (
          <FormField
            name="custom_config.vertex_credentials"
            state={apiStatus === "error" ? "error" : state}
            className="w-full"
          >
            <FormField.Label>Credentials File</FormField.Label>
            <FormField.Control>
              <InputFile
                setValue={(value) => helper.setValue(value)}
                error={apiStatus === "error"}
                onBlur={field.onBlur}
                showClearButton={true}
                disabled={disabled}
                accept="application/json"
                placeholder="Upload or paste your credentials"
              />
            </FormField.Control>
            {showApiMessage ? (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: `Testing credentials with ${imageProvider.title}...`,
                  success: "Credentials valid. Configuration saved.",
                  error: errorMessage || "Invalid credentials",
                }}
              />
            ) : (
              <FormField.Message
                messages={{
                  idle: (
                    <>
                      {"Upload or paste your "}
                      <InlineExternalLink href="https://console.cloud.google.com/projectselector2/iam-admin/serviceaccounts?supportedpurview=project">
                        service account credentials
                      </InlineExternalLink>
                      {" from Google Cloud."}
                    </>
                  ),
                  error: meta.error,
                }}
              />
            )}
          </FormField>
        )}
      />

      {/* Location field */}
      <FormikField<string>
        name="custom_config.vertex_location"
        render={(field, helper, meta, state) => (
          <FormField
            name="custom_config.vertex_location"
            state={state}
            className="w-full"
          >
            <FormField.Label>Location</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                value={field.value}
                onChange={(e) => helper.setValue(e.target.value)}
                onBlur={field.onBlur}
                placeholder="global"
                showClearButton={false}
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    {"The Google Cloud region for your Vertex AI models. See "}
                    <InlineExternalLink href="https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations">
                      Google&apos;s documentation
                    </InlineExternalLink>
                    {" for available regions."}
                  </>
                ),
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
  const { imageProvider, existingConfig } = props;

  return (
    <ImageGenFormWrapper<VertexImageGenFormValues>
      {...props}
      title={
        existingConfig
          ? `Edit ${imageProvider.title}`
          : `Connect ${imageProvider.title}`
      }
      description={imageProvider.description}
      initialValues={initialValues}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={(values) => transformValues(values, imageProvider)}
    >
      {(childProps) => <VertexFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
