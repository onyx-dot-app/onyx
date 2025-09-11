import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
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
import { LLM_CONTEXTUAL_COST_ADMIN_URL } from "../../configuration/llm/constants";
import { getDisplayNameForModel } from "@/lib/hooks";
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
    // Fetch contextual costs
    const { data: contextualCosts, error: costError } = useSWR<
      LLMContextualCost[]
    >(LLM_CONTEXTUAL_COST_ADMIN_URL, errorHandlingFetcher);

    const llmOptions: StringOrNumberOption[] = React.useMemo(
      () =>
        (contextualCosts || []).map((cost) => {
          return {
            name: getDisplayNameForModel(cost.model_name),
            value: cost.model_name,
          };
        }),
      [contextualCosts]
    );

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

    // Get the current value for the selector based on the parent state
    const getCurrentLLMValue = React.useMemo(() => {
      if (!advancedEmbeddingDetails.contextual_rag_llm_name) return null;
      return advancedEmbeddingDetails.contextual_rag_llm_name;
    }, [advancedEmbeddingDetails.contextual_rag_llm_name]);

    return (
      <div className="py-4 rounded-lg max-w-4xl px-4 mx-auto">
        <Formik
          innerRef={ref}
          initialValues={{
            ...advancedEmbeddingDetails,
            contextual_rag_llm: getCurrentLLMValue,
          }}
          validationSchema={Yup.object().shape({
            multilingual_expansion: Yup.array().of(Yup.string()),
            multipass_indexing: Yup.boolean(),
            enable_contextual_rag: Yup.boolean(),
            contextual_rag_llm: Yup.string()
              .nullable()
              .test(
                "required-if-contextual-rag",
                i18n.t(k.LLM_REQUIRED_FOR_CONTEXTUAL_RAG),
                function (value) {
                  const enableContextualRag = this.parent.enable_contextual_rag;
                  console.log("enableContextualRag", enableContextualRag);
                  console.log("value", value);
                  return !enableContextualRag || value !== null;
                }
              ),
            disable_rerank_for_streaming: Yup.boolean(),
            num_rerank: Yup.number()
              .required(i18n.t(k.RERANK_RESULTS_COUNT_REQUIRED))
              .min(1, i18n.t(k.MUST_BE_AT_LEAST_1)),
            embedding_precision: Yup.string().nullable(),
            reduced_dimension: Yup.number()
              .nullable()
              .test(
                "positive",
                i18n.t(k.MUST_BE_256_OR_HIGHER),
                (value) => value === null || value === undefined || value >= 256
              )
              .test(
                "openai",
                i18n.t(k.REDUCED_DIMENSIONS_OPENAI_ONLY),
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
              if (key === "contextual_rag_llm") {
                const selectedModel = (contextualCosts || []).find(
                  (cost) => cost.model_name === value
                );
                if (selectedModel) {
                  updateAdvancedEmbeddingDetails(
                    "contextual_rag_llm_provider",
                    selectedModel.provider
                  );
                  updateAdvancedEmbeddingDetails(
                    "contextual_rag_llm_name",
                    selectedModel.model_name
                  );
                }
              } else {
                updateAdvancedEmbeddingDetails(
                  key as keyof AdvancedSearchConfiguration,
                  value
                );
              }
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
                    enable_contextual_rag: Yup.boolean(),
                    contextual_rag_llm: Yup.string()
                      .nullable()
                      .test(
                        "required-if-contextual-rag",
                        i18n.t(k.LLM_REQUIRED_FOR_CONTEXTUAL_RAG),
                        function (value) {
                          const enableContextualRag =
                            this.parent.enable_contextual_rag;
                          console.log(
                            "enableContextualRag2",
                            enableContextualRag
                          );
                          console.log("value2", value);
                          return !enableContextualRag || value !== null;
                        }
                      ),
                    disable_rerank_for_streaming: Yup.boolean(),
                    num_rerank: Yup.number()
                      .required(i18n.t(k.RERANK_RESULTS_REQUIRED))
                      .min(1, i18n.t(k.MUST_BE_AT_LEAST_1)),
                    embedding_precision: Yup.string().nullable(),
                    Reduced_dimension: Yup.number()
                      .nullable()
                      .test(
                        "positive",
                        i18n.t(k.MUST_BE_256_OR_HIGHER),
                        (value) =>
                          value === null || value === undefined || value >= 256
                      )
                      .test(
                        "openai",
                        i18n.t(k.REDUCED_DIMENSIONS_OPENAI_ONLY_SHORT),
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
                    <Label>{i18n.t(k.MULTI_LINGUAL_EXPANSION)}</Label>

                    <SubLabel>
                      {i18n.t(k.ADD_ADDITIONAL_LANGUAGES_TO_TH)}
                    </SubLabel>
                    {values.multilingual_expansion.map(
                      (_: any, index: number) => (
                        <div key={index} className="w-full flex mb-4">
                          <Field
                            name={`${i18n.t(
                              k.MULTILINGUAL_EXPANSION1
                            )}${index}`}
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
                      {i18n.t(k.ADD_LANGUAGE)}
                    </button>
                  </div>
                )}
              </FieldArray>

              <BooleanFormField
                subtext={i18n.t(k.MULTIPASS_INDEXING_SUBTEXT)}
                optional
                label={i18n.t(k.MULTIPASS_INDEXING_LABEL)}
                name="multipass_indexing"
              />

              <BooleanFormField
                subtext={i18n.t(k.DISABLE_RERANK_STREAMING_SUBTEXT)}
                optional
                label={i18n.t(k.DISABLE_RERANK_STREAMING_LABEL)}
                name="disable_rerank_for_streaming"
              />

              <BooleanFormField
                subtext={i18n.t(k.CONTEXTUAL_RAG_SUBTEXT)}
                optional
                label={i18n.t(k.CONTEXTUAL_RAG_LABEL)}
                name="enable_contextual_rag"
              />

              <div>
                <SelectorFormField
                  name="contextual_rag_llm"
                  label={i18n.t(k.CONTEXTUAL_RAG_LLM_LABEL)}
                  subtext={
                    costError
                      ? i18n.t(k.ERROR_LOADING_LLM_MODELS_PLEA)
                      : !contextualCosts
                      ? i18n.t(k.LOADING_AVAILABLE_LLM_MODELS)
                      : values.enable_contextual_rag
                      ? i18n.t(k.SELECT_THE_LLM_MODEL_TO_USE_FO)
                      : i18n.t(k.ENABLE_CONTEXTUAL_RAG_ABOVE_TO)
                  }
                  options={llmOptions}
                  disabled={
                    !values.enable_contextual_rag ||
                    !contextualCosts ||
                    !!costError
                  }
                />

                {values.enable_contextual_rag &&
                  values.contextual_rag_llm &&
                  !costError && (
                    <div className="mt-2 text-sm text-text-600">
                      {contextualCosts ? (
                        <>
                          {i18n.t(k.ESTIMATED_COST_FOR_PROCESSING)}{" "}
                          {COST_CALCULATION_TOKENS.toLocaleString()}{" "}
                          {i18n.t(k.TOKENS1)}{" "}
                          <span className="font-medium">
                            {getSelectedModelCost(values.contextual_rag_llm)
                              ? formatCost(
                                  getSelectedModelCost(
                                    values.contextual_rag_llm
                                  )!.cost
                                )
                              : i18n.t(k.COST_INFORMATION_NOT_AVAILABLE)}
                          </span>
                        </>
                      ) : (
                        i18n.t(k.LOADING_COST_INFORMATION)
                      )}
                    </div>
                  )}
              </div>
              <NumberInput
                description={i18n.t(k.RERANK_RESULTS_DESCRIPTION)}
                optional={false}
                label={i18n.t(k.RERANK_RESULTS_LABEL)}
                name="num_rerank"
              />

              <SelectorFormField
                name="embedding_precision"
                label={i18n.t(k.EMBEDDING_PRECISION_LABEL)}
                options={embeddingPrecisionOptions}
                subtext={i18n.t(k.EMBEDDING_PRECISION_SUBTEXT)}
              />

              <NumberInput
                description={i18n.t(k.REDUCED_DIMENSION_DESCRIPTION)}
                optional={true}
                label={i18n.t(k.REDUCED_DIMENSION_LABEL)}
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
