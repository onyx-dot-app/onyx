import React, { forwardRef } from "react";
import { Formik, Form, FormikProps, FieldArray, Field } from "formik";
import * as Yup from "yup";
import { TrashIcon } from "@/components/icons/icons";
import { FaPlus } from "react-icons/fa";
import {
  AdvancedSearchConfiguration,
  EmbeddingPrecision,
  LLMContextualCost,
} from "../interfaces";
import {
  BooleanFormField,
  Label,
  SubLabel,
  SelectorFormField,
} from "@/components/admin/connectors/Field";
import NumberInput from "../../connectors/[connector]/pages/ConnectorInput/NumberInput";
import { StringOrNumberOption } from "@/components/Dropdown";
import useSWR from "swr";
import { LLM_PROVIDERS_ADMIN_URL } from "../../configuration/llm/constants";
import { getDisplayNameForModel } from "@/lib/hooks";
import { LLMProviderDescriptor } from "../../configuration/llm/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

// Number of tokens to show cost calculation for
const COST_CALCULATION_TOKENS = 1_000_000;

interface AdvancedEmbeddingFormPageProps {
  updateAdvancedEmbeddingDetails: (
    key: keyof AdvancedSearchConfiguration,
    value: any
  ) => void;
  advancedEmbeddingDetails: AdvancedSearchConfiguration;
  embeddingProviderType: string | null;
  onValidationChange?: (
    isValid: boolean,
    errors: Record<string, string>
  ) => void;
}

// Options for embedding precision based on EmbeddingPrecision enum
const embeddingPrecisionOptions: StringOrNumberOption[] = [
  { name: EmbeddingPrecision.BFLOAT16, value: EmbeddingPrecision.BFLOAT16 },
  { name: EmbeddingPrecision.FLOAT, value: EmbeddingPrecision.FLOAT },
];

const AdvancedEmbeddingFormPage = forwardRef<
  FormikProps<any>,
  AdvancedEmbeddingFormPageProps
>(
  (
    {
      updateAdvancedEmbeddingDetails,
      advancedEmbeddingDetails,
      embeddingProviderType,
      onValidationChange,
    },
    ref
  ) => {
    // Fetch available LLM providers
    const { data: llmProviders, error: llmError } = useSWR<
      LLMProviderDescriptor[]
    >(LLM_PROVIDERS_ADMIN_URL, errorHandlingFetcher);

    // Fetch contextual costs
    const { data: contextualCosts, error: costError } = useSWR<
      LLMContextualCost[]
    >("/api/admin/llm/provider-contextual-cost", errorHandlingFetcher);

    console.log(contextualCosts);

    // Create options array from available models, removing duplicates
    const llmOptions: StringOrNumberOption[] = React.useMemo(() => {
      if (!llmProviders) return [];

      const seenModels = new Set<string>();
      const options: StringOrNumberOption[] = [];

      llmProviders.forEach((provider) => {
        (provider.display_model_names || provider.model_names).forEach(
          (modelName) => {
            const displayName = getDisplayNameForModel(modelName);
            if (!seenModels.has(displayName)) {
              seenModels.add(displayName);
              options.push({
                name: displayName,
                value: modelName,
              });
            }
          }
        );
      });

      return options;
    }, [llmProviders]);

    // Helper function to format cost as USD
    const formatCost = (cost: number) => {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(cost);
    };

    // Get cost info for selected model
    const getSelectedModelCost = (modelName: string | null) => {
      if (!contextualCosts || !modelName) return null;
      return contextualCosts.find((cost) => cost.model_name === modelName);
    };

    return (
      <div className="py-4 rounded-lg max-w-4xl px-4 mx-auto">
        <Formik
          innerRef={ref}
          initialValues={advancedEmbeddingDetails}
          validationSchema={Yup.object().shape({
            multilingual_expansion: Yup.array().of(Yup.string()),
            multipass_indexing: Yup.boolean(),
            enable_contextual_rag: Yup.boolean(),
            contextual_rag_llm: Yup.string().nullable(),
            disable_rerank_for_streaming: Yup.boolean(),
            num_rerank: Yup.number()
              .required("Number of results to rerank is required")
              .min(1, "Must be at least 1"),
            embedding_precision: Yup.string().nullable(),
            reduced_dimension: Yup.number()
              .nullable()
              .test(
                "positive",
                "Must be larger than or equal to 256",
                (value) => value === null || value === undefined || value >= 256
              )
              .test(
                "openai",
                "Reduced Dimensions is only supported for OpenAI embedding models",
                (value) => {
                  return embeddingProviderType === "openai" || value === null;
                }
              ),
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

            // Run validation and report errors
            if (onValidationChange) {
              // We'll return an empty object here since Yup will handle the actual validation
              // But we need to check if there are any validation errors
              const errors: Record<string, string> = {};
              try {
                // Manually validate against the schema
                Yup.object()
                  .shape({
                    multilingual_expansion: Yup.array().of(Yup.string()),
                    multipass_indexing: Yup.boolean(),
                    disable_rerank_for_streaming: Yup.boolean(),
                    num_rerank: Yup.number()
                      .required("Number of results to rerank is required")
                      .min(1, "Must be at least 1"),
                    embedding_precision: Yup.string().nullable(),
                    reduced_dimension: Yup.number()
                      .nullable()
                      .test(
                        "positive",
                        "Must be larger than or equal to 256",
                        (value) =>
                          value === null || value === undefined || value >= 256
                      )
                      .test(
                        "openai",
                        "Reduced Dimensions is only supported for OpenAI embedding models",
                        (value) => {
                          return (
                            embeddingProviderType === "openai" || value === null
                          );
                        }
                      ),
                  })
                  .validateSync(values, { abortEarly: false });
                onValidationChange(true, {});
              } catch (validationError) {
                if (validationError instanceof Yup.ValidationError) {
                  validationError.inner.forEach((err) => {
                    if (err.path) {
                      errors[err.path] = err.message;
                    }
                  });
                  onValidationChange(false, errors);
                }
              }
            }

            return {}; // Return empty object as Formik will handle the errors
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
              <BooleanFormField
                subtext="Enable contextual RAG for all chunk sizes."
                optional
                label="Contextual RAG"
                name="enable_contextual_rag"
              />
              <div>
                <SelectorFormField
                  name="contextual_rag_llm"
                  label="Contextual RAG LLM"
                  subtext={
                    llmError
                      ? "Error loading LLM models. Please try again later."
                      : !llmProviders
                        ? "Loading available LLM models..."
                        : values.enable_contextual_rag
                          ? "Select the LLM model to use for contextual RAG processing."
                          : "Enable Contextual RAG above to select an LLM model."
                  }
                  options={llmOptions}
                  disabled={
                    !values.enable_contextual_rag || !llmProviders || !!llmError
                  }
                />
                {values.enable_contextual_rag &&
                  values.contextual_rag_llm &&
                  !costError && (
                    <div className="mt-2 text-sm text-text-600">
                      {contextualCosts ? (
                        <>
                          Estimated cost for processing{" "}
                          {COST_CALCULATION_TOKENS.toLocaleString()} tokens:{" "}
                          <span className="font-medium">
                            {getSelectedModelCost(values.contextual_rag_llm)
                              ? formatCost(
                                  getSelectedModelCost(
                                    values.contextual_rag_llm
                                  )!.cost
                                )
                              : "Cost information not available"}
                          </span>
                        </>
                      ) : (
                        "Loading cost information..."
                      )}
                    </div>
                  )}
              </div>
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
              If not specified, will just use the selected model's default dimensionality without any reduction. 
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
  }
);
export default AdvancedEmbeddingFormPage;

AdvancedEmbeddingFormPage.displayName = "AdvancedEmbeddingFormPage";
