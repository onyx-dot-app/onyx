import React, { forwardRef } from "react";
import { Formik, Form, FormikProps, FieldArray, Field } from "formik";
import * as Yup from "yup";
import { TrashIcon } from "@/components/icons/icons";
import { FaPlus } from "react-icons/fa";
import { AdvancedSearchConfiguration, EmbeddingPrecision } from "../interfaces";
import {
  BooleanFormField,
  Label,
  SubLabel,
  SelectorFormField,
} from "@/components/admin/connectors/Field";
import NumberInput from "../../connectors/[connector]/pages/ConnectorInput/NumberInput";
import { StringOrNumberOption } from "@/components/Dropdown";

interface AdvancedEmbeddingFormPageProps {
  updateAdvancedEmbeddingDetails: (
    key: keyof AdvancedSearchConfiguration,
    value: any
  ) => void;
  advancedEmbeddingDetails: AdvancedSearchConfiguration;
}

// Options for embedding precision based on EmbeddingPrecision enum
const embeddingPrecisionOptions: StringOrNumberOption[] = [
  { name: EmbeddingPrecision.INT8, value: EmbeddingPrecision.INT8 },
  { name: EmbeddingPrecision.BFLOAT16, value: EmbeddingPrecision.BFLOAT16 },
  { name: EmbeddingPrecision.FLOAT, value: EmbeddingPrecision.FLOAT },
  { name: EmbeddingPrecision.DOUBLE, value: EmbeddingPrecision.DOUBLE },
];

const AdvancedEmbeddingFormPage = forwardRef<
  FormikProps<any>,
  AdvancedEmbeddingFormPageProps
>(({ updateAdvancedEmbeddingDetails, advancedEmbeddingDetails }, ref) => {
  return (
    <div className="py-4 rounded-lg max-w-4xl px-4 mx-auto">
      <Formik
        innerRef={ref}
        initialValues={advancedEmbeddingDetails}
        validationSchema={Yup.object().shape({
          multilingual_expansion: Yup.array().of(Yup.string()),
          multipass_indexing: Yup.boolean(),
          disable_rerank_for_streaming: Yup.boolean(),
          num_rerank: Yup.number(),
          embedding_precision: Yup.string().nullable(),
          reduced_dimension: Yup.number().nullable(),
        })}
        onSubmit={async (_, { setSubmitting }) => {
          setSubmitting(false);
        }}
        validate={(values) => {
          // Call updateAdvancedEmbeddingDetails for each changed field
          Object.entries(values).forEach(([key, value]) => {
            updateAdvancedEmbeddingDetails(
              key as keyof AdvancedSearchConfiguration,
              value
            );
          });
        }}
        enableReinitialize={true}
      >
        {({ values }) => (
          <Form>
            <FieldArray name="multilingual_expansion">
              {({ push, remove }) => (
                <div className="w-full">
                  <Label>Multi-lingual Expansion</Label>

                  <SubLabel>Add additional languages to the search.</SubLabel>
                  {values.multilingual_expansion.map(
                    (_: any, index: number) => (
                      <div key={index} className="w-full flex mb-4">
                        <Field
                          name={`multilingual_expansion.${index}`}
                          className={`w-full bg-input text-sm p-2  border border-border-medium rounded-md
                                      focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mr-2`}
                        />
                        <button
                          type="button"
                          onClick={() => remove(index)}
                          className={`p-2 my-auto bg-input flex-none rounded-md 
                              bg-red-500 text-white hover:bg-red-600
                              focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-opacity-50`}
                        >
                          <TrashIcon className="text-white my-auto" />
                        </button>
                      </div>
                    )
                  )}
                  <button
                    type="button"
                    onClick={() => push("")}
                    className={`mt-2 p-2 bg-rose-500 text-xs text-white rounded-md flex items-center
                        hover:bg-rose-600 focus:outline-none focus:ring-2 focus:ring-rose-500 focus:ring-opacity-50`}
                  >
                    <FaPlus className="mr-2" />
                    Add Language
                  </button>
                </div>
              )}
            </FieldArray>

            <BooleanFormField
              subtext="Enable multipass indexing for both mini and large chunks."
              optional
              label="Multipass Indexing"
              name="multipass_indexing"
            />
            <BooleanFormField
              subtext="Disable reranking for streaming to improve response time."
              optional
              label="Disable Rerank for Streaming"
              name="disable_rerank_for_streaming"
            />
            <NumberInput
              description="Number of results to rerank"
              optional={false}
              label="Number of Results to Rerank"
              name="num_rerank"
            />

            <SelectorFormField
              name="embedding_precision"
              label="Embedding Precision"
              options={embeddingPrecisionOptions}
              subtext="Select the precision for embedding vectors. Lower precision uses less storage but may reduce accuracy."
            />

            <NumberInput
              description="Number of dimensions to reduce the embedding to. 
              Will reduce memory usage but may reduce accuracy. 
              If not specified, will just use the model_dim without any reduction. 
              Currently only supported for OpenAI embedding models"
              optional={true}
              label="Reduced Dimension"
              name="reduced_dimension"
            />
          </Form>
        )}
      </Formik>
    </div>
  );
});
export default AdvancedEmbeddingFormPage;

AdvancedEmbeddingFormPage.displayName = "AdvancedEmbeddingFormPage";
