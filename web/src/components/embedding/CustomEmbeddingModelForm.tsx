import {
  CloudEmbeddingModel,
  EmbeddingProvider,
  getFormattedProviderName,
} from "./interfaces";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { TextFormField, BooleanFormField } from "@/components/Field";
import { Dispatch, SetStateAction } from "react";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";
import { EmbeddingDetails } from "@/app/admin/embeddings/EmbeddingModelSelectionForm";

export function CustomEmbeddingModelForm({
  setShowTentativeModel,
  currentValues,
  provider,
  embeddingType,
}: {
  setShowTentativeModel: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  currentValues: CloudEmbeddingModel | null;
  provider: EmbeddingDetails;
  embeddingType: EmbeddingProvider;
}) {
  return (
    <div>
      <Formik
        initialValues={
          currentValues || {
            model_name: "",
            model_dim: 768,
            normalize: false,
            query_prefix: "",
            passage_prefix: "",
            provider_type: embeddingType,
            api_key: "",
            enabled: true,
            api_url: provider.api_url,
            description: "",
            index_name: "",
          }
        }
        validationSchema={Yup.object().shape({
          model_name: Yup.string().required("Model name is required"),
          model_dim: Yup.number().required("Model dimension is required"),
          normalize: Yup.boolean().required(),
          query_prefix: Yup.string(),
          passage_prefix: Yup.string(),
          provider_type: Yup.string().required("Provider type is required"),
          api_key: Yup.string().optional(),
          enabled: Yup.boolean(),
          api_url: Yup.string().required("API base URL is required"),
          description: Yup.string(),
          index_name: Yup.string().nullable(),
        })}
        onSubmit={async (values) => {
          setShowTentativeModel(values as CloudEmbeddingModel);
        }}
      >
        {({ isSubmitting, submitForm, errors }) => (
          <Form>
            <Text className="text-xl text-text-900 font-bold mb-4">
              Specify details for your {getFormattedProviderName(embeddingType)}{" "}
              Provider&apos;s model
            </Text>
            <TextFormField
              name="model_name"
              label="Model Name:"
              subtext={`The name of the ${getFormattedProviderName(
                embeddingType
              )} model`}
              placeholder="e.g. 'all-MiniLM-L6-v2'"
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="model_dim"
              label="Model Dimension:"
              subtext="The dimension of the model's embeddings"
              placeholder="e.g. '1536'"
              type="number"
              autoCompleteDisabled={true}
            />

            <BooleanFormField
              removeIndent
              name="normalize"
              label="Normalize"
              subtext="Whether to normalize the embeddings"
            />

            <TextFormField
              name="query_prefix"
              label="Query Prefix:"
              subtext="Prefix for query embeddings"
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="passage_prefix"
              label="Passage Prefix:"
              subtext="Prefix for passage embeddings"
              autoCompleteDisabled={true}
            />

            <Button
              type="submit"
              disabled={isSubmitting}
              className="w-64 mx-auto"
            >
              Configure {getFormattedProviderName(embeddingType)} Model
            </Button>
          </Form>
        )}
      </Formik>
    </div>
  );
}
