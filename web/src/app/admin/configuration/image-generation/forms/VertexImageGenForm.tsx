"use client";

import * as Yup from "yup";
import { Form } from "formik";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "./types";
import { FileUploadFormField, TextFormField } from "@/components/Field";
import { ImageGenFormWrapper } from "./ImageGenFormWrapper";
import { ImageProvider } from "../constants";
import { ImageGenerationCredentials } from "@/lib/configuration/imageConfigurationService";

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
    vertex_location: "",
  },
};

const validationSchema = Yup.object().shape({
  custom_config: Yup.object().shape({
    vertex_credentials: Yup.string().required("Credentials file is required"),
    vertex_location: Yup.string(),
  }),
});

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  imageProvider: ImageProvider
): Partial<VertexImageGenFormValues> {
  return initialValues;
}

function transformValues(
  values: VertexImageGenFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: "vertex_ai",
    customConfig: {
      vertex_credentials: values.custom_config.vertex_credentials,
      vertex_location: values.custom_config.vertex_location,
    },
  };
}

function VertexFormFields(
  props: ImageGenFormChildProps<VertexImageGenFormValues>
) {
  return (
    <Form>
      <FileUploadFormField
        name="custom_config.vertex_credentials"
        label="Credentials File"
        subtext="Upload your Google Cloud service account JSON credentials file."
      />
      <TextFormField
        name="custom_config.vertex_location"
        label="Location"
        placeholder="global"
        subtext="The Google Cloud region for your Vertex AI models (e.g., global, us-east1, us-central1, europe-west1). See [Google's documentation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations#google_model_endpoint_locations) to find the appropriate region for your model."
      />
    </Form>
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
